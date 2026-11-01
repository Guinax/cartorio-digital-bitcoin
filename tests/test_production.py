import copy
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cryptography.fernet import Fernet

from cartorio_documentos.backup import create_backup, restore_backup
from cartorio_documentos.production import DEFAULTS, MAINNET_GENESIS, doctor, load_config, node_for
from cartorio_documentos.registry import Registry, RegistryError, fingerprint, now, verify_receipt
from cartorio_documentos.security import NoRedirect, atomic_private, private_read
from cartorio_documentos.worker import run_once

PASSWORD = b"synthetic-passphrase-for-tests-only"
NODE_ID = "02" + "11" * 32


class BitcoinFixture:
    def __init__(self):
        self.info = {"chain": "main", "initialblockdownload": False, "blocks": 800000,
                     "headers": 800000, "time": int(time.time())}
        self.genesis = MAINNET_GENESIS

    def call(self, method, *params):
        if method == "getblockchaininfo":
            return self.info
        if method == "getblockhash" and params == (0,):
            return self.genesis
        raise AssertionError(method)


class LightningFixture:
    def __init__(self):
        self.info = {"network": "bitcoin", "id": NODE_ID, "blockheight": 800000}
        self.channels = [{"state": "CHANNELD_NORMAL", "peer_connected": True, "receivable_msat": 10000000}]

    def call(self, method, **params):
        if method == "getinfo":
            return self.info
        if method == "listpeerchannels":
            return {"channels": self.channels}
        raise AssertionError(method)


class ProductionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.registry = Registry(self.data, network="bitcoin", password=PASSWORD, require_encrypted_key=True)
        self.registry.initialize()
        self.document = self.root / "sample.txt"
        self.document.write_bytes(b"Synthetic document, no personal information.")
        self.receipt = self.registry.register(self.document)
        self.id = self.receipt["payload"]["record_id"]
        self.identity = fingerprint(self.registry.key().public_key())
        self.config = {**DEFAULTS, "data_dir": self.data, "key_password_file": self.root / "password",
                       "backup_dir": self.root / "backups", "backup_key_file": self.root / "backup.key",
                       "bitcoin_cookie_file": self.root / "cookie", "bitcoin_rpc_url": "http://127.0.0.1:8332",
                       "lightning_rest_url": "https://localhost:3010", "lightning_rune_file": self.root / "rune",
                       "lightning_ca_file": self.root / "ca.pem", "lightning_node_id": NODE_ID}
        for key, value in {"key_password_file": PASSWORD, "backup_key_file": Fernet.generate_key(),
                           "bitcoin_cookie_file": b"__cookie__:synthetic", "lightning_rune_file": b"synthetic-rune"}.items():
            atomic_private(self.config[key], value)
        atomic_private(self.data / "worker-status.json", json.dumps({"checked_at": now(), "network": "bitcoin"}).encode())
        self.backup = create_backup(self.registry, self.config["backup_dir"], self.config["backup_key_file"])
        self.rpc, self.node = BitcoinFixture(), LightningFixture()

    def tearDown(self):
        self.tmp.cleanup()

    def diagnose(self):
        return doctor(self.config, self.registry, rpc=self.rpc, node=self.node)

    def test_encrypted_key_cannot_be_opened_without_correct_password(self):
        self.assertIn(b"ENCRYPTED PRIVATE KEY", self.registry.key_path.read_bytes())
        for password in (None, b"wrong-password"):
            with self.subTest(password=password), self.assertRaises(RegistryError):
                Registry(self.data, password=password).key()

    def test_protect_legacy_key_preserves_identity_and_old_receipts(self):
        old = Registry(self.root / "legacy")
        old.initialize()
        receipt = old.register(self.document)
        public = (old.directory / "issuer-public.pem").read_bytes()
        secured = Registry(old.directory, password=PASSWORD)
        secured.protect_key()
        self.assertIn(b"ENCRYPTED PRIVATE KEY", secured.key_path.read_bytes())
        self.assertTrue(verify_receipt(receipt, self.document, public)["signature_valid"])

    def test_backup_round_trip_restores_same_issuer_and_document(self):
        target = self.root / "restored"
        result = restore_backup(self.backup["path"], target, self.config["backup_key_file"], PASSWORD, self.identity)
        restored = Registry(target, password=PASSWORD, require_encrypted_key=True)
        receipt = restored.receipt(self.id)
        self.assertEqual(result["records"], 1)
        self.assertEqual(receipt["payload"]["document"], self.receipt["payload"]["document"])
        self.assertEqual(fingerprint(restored.key().public_key()), self.identity)
        self.assertEqual(restored.key_path.stat().st_mode & 0o777, 0o600)

    def test_restore_never_overwrites_existing_data(self):
        before = self.registry.db_path.read_bytes()
        with self.assertRaises(RegistryError):
            restore_backup(self.backup["path"], self.data, self.config["backup_key_file"], PASSWORD, self.identity)
        self.assertEqual(self.registry.db_path.read_bytes(), before)

    def test_wrong_password_wrong_issuer_or_modified_backup_rejected(self):
        for password, identity in ((b"wrong", self.identity), (PASSWORD, "00" * 32)):
            with self.subTest(identity=identity), self.assertRaises(RegistryError):
                restore_backup(self.backup["path"], self.root / "restore-bad", self.config["backup_key_file"], password, identity)
        archive = Path(self.backup["path"])
        archive.write_bytes(archive.read_bytes()[:-16] + b"modified-archive!")
        with self.assertRaises(RegistryError):
            restore_backup(archive, self.root / "restore-bad", self.config["backup_key_file"], PASSWORD, self.identity)
        self.assertFalse((self.root / "restore-bad").exists())

    def test_doctor_requires_every_operational_check_and_does_not_enable_invoices(self):
        result = self.diagnose()
        self.assertTrue(result["ready_for_receiving"])
        self.assertFalse(result["mainnet_invoices_enabled"])

    def test_wrong_chain_stale_tip_or_unsynced_core_blocks_receiving(self):
        changes = [{"chain": "regtest"}, {"initialblockdownload": True}, {"time": 1}, {"headers": 800010}]
        original = copy.deepcopy(self.rpc.info)
        for change in changes:
            self.rpc.info = {**original, **change}
            with self.subTest(change=change):
                self.assertFalse(self.diagnose()["ready_for_receiving"])
        self.rpc.info = original
        self.rpc.genesis = "00" * 32
        self.assertFalse(self.diagnose()["ready_for_receiving"])

    def test_pruned_bitcoin_core_keeps_a_safe_window_for_lightning(self):
        self.rpc.info.update({"pruned": True, "pruneheight": 799000})
        self.assertTrue(self.diagnose()["ready_for_receiving"])
        self.rpc.info["pruneheight"] = 799900
        self.assertFalse(self.diagnose()["ready_for_receiving"])
        self.rpc.info["pruneheight"] = 800000
        self.assertFalse(self.diagnose()["ready_for_receiving"])
        self.rpc.info["pruneheight"] = -1
        self.assertFalse(self.diagnose()["ready_for_receiving"])
        self.rpc.info.pop("pruneheight")
        self.assertFalse(self.diagnose()["ready_for_receiving"])
        self.rpc.info["pruneheight"] = 799000
        self.node.info["blockheight"] = 799010
        self.assertFalse(self.diagnose()["ready_for_receiving"])

    def test_wrong_lightning_identity_warning_or_no_inbound_blocks_receiving(self):
        original = copy.deepcopy(self.node.info)
        for change in ({"id": "03" + "22" * 32}, {"network": "regtest"}, {"warning_bitcoind_sync": "syncing"}):
            self.node.info = {**original, **change}
            with self.subTest(change=change):
                self.assertFalse(self.diagnose()["ready_for_receiving"])
        self.node.info = original
        self.node.channels[0]["peer_connected"] = False
        self.assertFalse(self.diagnose()["ready_for_receiving"])

    def test_missing_backup_heartbeat_or_public_secret_blocks_receiving(self):
        heartbeat = self.data / "worker-status.json"
        saved = heartbeat.read_bytes()
        heartbeat.unlink()
        self.assertFalse(self.diagnose()["ready_for_receiving"])
        atomic_private(heartbeat, saved)
        Path(self.backup["path"]).unlink()
        self.assertFalse(self.diagnose()["ready_for_receiving"])
        os.chmod(self.config["lightning_rune_file"], 0o644)
        with self.assertRaises(RegistryError):
            private_read(self.config["lightning_rune_file"])

    def test_mainnet_invoice_gate_paused_cap_and_unhealthy_checks(self):
        with patch("cartorio_documentos.production.CoreLightningREST", return_value=Mock()) as factory:
            client = node_for(self.config, self.registry)
            with self.assertRaises(RegistryError):
                client.invoice_gate(1000)
            self.config["allow_mainnet_invoices"] = True
            with self.assertRaises(RegistryError):
                client.invoice_gate(self.config["max_invoice_msat"] + 1)
            with patch("cartorio_documentos.production.doctor", return_value={"ready_for_receiving": False, "checks": [{"name": "bitcoin", "ok": False}]}):
                with self.assertRaises(RegistryError):
                    client.invoice_gate(1000)
            with patch("cartorio_documentos.production.doctor", return_value={"ready_for_receiving": True}):
                client.invoice_gate(1000)

    def test_persistent_queue_retries_pending_proof_without_claiming_verification(self):
        with patch("cartorio_documentos.worker.stamp") as submit, patch("cartorio_documentos.worker.upgrade"), \
             patch("cartorio_documentos.worker.verify_bitcoin", side_effect=RegistryError("pending")):
            first = run_once(self.config, self.registry, node=self.node, rpc=self.rpc)
            second = run_once(self.config, self.registry, node=self.node, rpc=self.rpc)
            self.assertEqual(first["pending_verification"], 1)
            self.assertEqual(first["verified"], 0)
            self.assertEqual(second["processed"], 0)
            self.assertEqual(submit.call_count, 1)

    def test_config_rejects_unknown_fields_and_fee_above_cap(self):
        raw = {key: str(value) if isinstance(value, Path) else value for key, value in self.config.items()}
        path = self.root / "config.json"
        path.write_text(json.dumps(raw))
        self.assertEqual(load_config(path)["lightning_node_id"], NODE_ID)
        raw["unknown_option"] = True
        path.write_text(json.dumps(raw))
        with self.assertRaises(RegistryError):
            load_config(path)
        del raw["unknown_option"]
        raw["service_fee_msat"] = raw["max_invoice_msat"] + 1
        path.write_text(json.dumps(raw))
        with self.assertRaises(RegistryError):
            load_config(path)

    def test_failed_submission_is_retained_and_retry_is_delayed(self):
        with patch("cartorio_documentos.worker.stamp", side_effect=RegistryError("calendar unavailable")) as submit:
            first = run_once(self.config, self.registry, node=self.node, rpc=self.rpc)
            second = run_once(self.config, self.registry, node=self.node, rpc=self.rpc)
            self.assertEqual(first["errors"], 1)
            self.assertFalse(first["health"]["ready_for_receiving"])
            self.assertEqual(second["processed"], 0)
            self.assertFalse(second["health"]["ready_for_receiving"])
            self.assertEqual(submit.call_count, 1)
            with self.registry.connection() as db:
                job = db.execute("SELECT failures, next_run_at FROM processing_jobs WHERE record_id = ?", (self.id,)).fetchone()
            self.assertEqual(job["failures"], 1)
            self.assertGreater(job["next_run_at"], time.time())
    def test_redirect_never_forwards_authentication(self):
        with self.assertRaises(RegistryError):
            NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://other.example")
