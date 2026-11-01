from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bitcoin.core import CBlockHeader, b2lx
from opentimestamps.core.notary import BitcoinBlockHeaderAttestation, PendingAttestation
from opentimestamps.core.op import OpSHA256
from opentimestamps.core.timestamp import DetachedTimestampFile, Timestamp

from cartorio_documentos.lightning import CoreLightning, forwarding_report, invoice_for, sync_payment
from cartorio_documentos.ots import BitcoinRPC, deserialize, serialize, stamp, upgrade, verify_bitcoin
from cartorio_documentos.registry import Registry, RegistryError, verify_receipt


class FakeNode:
    network = "regtest"

    def __init__(self):
        self.invoices = []
        self.preimage = bytes.fromhex("12" * 32)
        self.forward_data = []

    def ensure_network(self, expected):
        if expected != self.network:
            raise RegistryError("Rede incorreta")

    def call(self, method, **params):
        if method == "listinvoices":
            return {"invoices": copy.deepcopy(self.invoices)}
        if method == "invoice":
            self.invoices.append({"label": params["label"], "amount_msat": params["amount_msat"],
                "payment_hash": hashlib.sha256(self.preimage).hexdigest(), "expires_at": 1800000000,
                "bolt11": "lnbcrt1mock-for-unit-test-only", "status": "unpaid"})
            return copy.deepcopy(self.invoices[0])
        if method == "listforwards":
            return {"forwards": self.forward_data}
        raise AssertionError(method)

    def pay(self):
        self.invoices[0].update(status="paid", amount_received_msat=2500, paid_at=1790000000,
                                payment_preimage=self.preimage.hex())


class FakeCalendar:
    calls = 0
    def __init__(self, url):
        self.url = url

    def submit(self, digest, timeout):
        FakeCalendar.calls += 1
        proof = Timestamp(digest)
        proof.attestations.add(PendingAttestation("https://alice.btc.calendar.opentimestamps.org"))
        return proof

    def get_timestamp(self, commitment, timeout):
        proof = Timestamp(commitment)
        proof.attestations.add(BitcoinBlockHeaderAttestation(100))
        return proof


class FakeBitcoin:
    def __init__(self, message, *, chain="main", blocks=110, ibd=False, reorg=False):
        self.header = CBlockHeader(nVersion=1, hashMerkleRoot=message, nTime=1700000000, nBits=0x1D00FFFF)
        self.chain, self.blocks, self.ibd, self.reorg = chain, blocks, ibd, reorg
        self.hash_calls = 0

    def call(self, method, *params):
        if method == "getblockchaininfo":
            return {"chain": self.chain, "blocks": self.blocks, "initialblockdownload": self.ibd}
        if method == "getblockhash":
            self.hash_calls += 1
            return "00" * 32 if self.reorg and self.hash_calls > 1 else b2lx(self.header.GetHash())
        if method == "getblockheader":
            return self.header.serialize().hex()
        raise AssertionError(method)


class DocumentsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.file = self.root / "contrato.txt"
        self.file.write_bytes(b"Contrato de teste; nenhum dado pessoal.\n")
        self.registry = Registry(self.root / "state")
        self.registry.initialize()
        self.receipt = self.registry.register(self.file)
        self.id = self.receipt["payload"]["record_id"]
        self.public = (self.root / "state" / "issuer-public.pem").read_bytes()

    def tearDown(self):
        self.temp.cleanup()

    def confirmed_proof(self, message=None):
        digest = self.registry.get(self.id)["sha256"]
        proof = DetachedTimestampFile(OpSHA256(), Timestamp(bytes.fromhex(digest)))
        proof.timestamp.attestations.add(BitcoinBlockHeaderAttestation(100))
        self.registry.update(self.id, proof=serialize(proof))
        return bytes.fromhex(digest) if message is None else message

    def paid_registry(self):
        registry = Registry(self.root / "paid-state", fee_msat=2500)
        registry.initialize()
        record = registry.register(self.file)
        return registry, record["payload"]["record_id"]

    def test_receipt_signature_file_hash_and_reinitialization(self):
        result = verify_receipt(self.receipt, self.file, self.public)
        self.assertTrue(result["document_matches"])
        self.assertFalse(result["bitcoin_proof_verified_now"])
        before = self.registry.key_path.read_bytes()
        self.registry.initialize()
        self.assertEqual(self.registry.key_path.read_bytes(), before)

    def test_duplicate_document_does_not_duplicate_registration(self):
        self.assertEqual(self.registry.register(self.file)["payload"]["record_id"], self.id)

    def test_changed_document_and_tampered_receipt_are_rejected(self):
        self.file.write_bytes(b"Documento alterado")
        with self.assertRaises(RegistryError):
            verify_receipt(self.receipt, self.file, self.public)
        changed = copy.deepcopy(self.receipt)
        changed["payload"]["document"]["sha256"] = hashlib.sha256(self.file.read_bytes()).hexdigest()
        changed["payload"]["document"]["size_bytes"] = self.file.stat().st_size
        with self.assertRaises(RegistryError):
            verify_receipt(changed, self.file, self.public)

    def test_untrusted_key_is_rejected(self):
        other = Registry(self.root / "other")
        other.initialize()
        with self.assertRaises(RegistryError):
            verify_receipt(self.receipt, self.file, (other.directory / "issuer-public.pem").read_bytes())

    def test_lost_key_is_not_silently_replaced(self):
        self.registry.key_path.unlink()
        with self.assertRaises(RegistryError):
            self.registry.initialize()

    def test_private_key_file_is_private(self):
        self.assertEqual(self.registry.key_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.registry.db_path.stat().st_mode & 0o777, 0o600)

    def test_database_does_not_contain_original_document(self):
        self.assertNotIn(self.file.read_bytes(), self.registry.db_path.read_bytes())

    def test_stamp_pending_is_not_bitcoin_confirmation(self):
        FakeCalendar.calls = 0
        receipt = stamp(self.registry, self.id, remote_factory=FakeCalendar)
        self.assertEqual(receipt["payload"]["bitcoin"]["status"], "pending")
        self.assertIsNone(receipt["payload"]["bitcoin"]["last_verification"])
        proof_before = self.registry.get(self.id)["proof"]
        stamp(self.registry, self.id, remote_factory=FakeCalendar)
        self.assertEqual(self.registry.get(self.id)["proof"], proof_before)
        self.assertEqual(FakeCalendar.calls, 2)

    def test_failed_calendars_do_not_create_fake_proof(self):
        class Offline(FakeCalendar):
            def submit(self, *args, **kwargs):
                raise OSError("offline")
        with self.assertRaises(RegistryError):
            stamp(self.registry, self.id, remote_factory=Offline)
        self.assertIsNone(self.registry.get(self.id)["proof"])

    def test_unpaid_service_cannot_be_stamped(self):
        registry, record_id = self.paid_registry()
        with self.assertRaises(RegistryError):
            stamp(registry, record_id, remote_factory=FakeCalendar)

    def test_upgrade_merges_attestation_without_claiming_confirmation(self):
        stamp(self.registry, self.id, remote_factory=FakeCalendar)
        upgrade(self.registry, self.id, remote_factory=FakeCalendar)
        row = self.registry.get(self.id)
        proof = deserialize(row["proof"], row["sha256"])
        self.assertTrue(any(isinstance(a, BitcoinBlockHeaderAttestation) for m, a in proof.timestamp.all_attestations()))
        self.assertEqual(self.registry.receipt(self.id)["payload"]["bitcoin"]["status"], "pending")

    def test_bitcoin_merkle_header_confirmation_and_reorg_checks(self):
        message = self.confirmed_proof()
        verified = verify_bitcoin(self.registry, self.id, FakeBitcoin(message))
        self.assertEqual(verified["payload"]["bitcoin"]["last_verification"]["height"], 100)
        with self.assertRaises(RegistryError):
            verify_bitcoin(self.registry, self.id, FakeBitcoin(message, reorg=True))
        self.assertIsNone(self.registry.get(self.id)["bitcoin_verification"])

    def test_wrong_merkle_root_wrong_chain_ibd_or_few_confirmations_rejected(self):
        message = self.confirmed_proof()
        for rpc in [FakeBitcoin(bytes(32)), FakeBitcoin(message, chain="regtest"),
                    FakeBitcoin(message, ibd=True), FakeBitcoin(message, blocks=101)]:
            with self.subTest(rpc=rpc):
                with self.assertRaises(RegistryError):
                    verify_bitcoin(self.registry, self.id, rpc)
        self.assertIsNone(self.registry.get(self.id)["bitcoin_verification"])

    def test_wrong_document_ots_cannot_be_attached(self):
        proof = DetachedTimestampFile(OpSHA256(), Timestamp(bytes(32)))
        proof.timestamp.attestations.add(BitcoinBlockHeaderAttestation(100))
        self.registry.update(self.id, proof=serialize(proof))
        with self.assertRaises(RegistryError):
            verify_bitcoin(self.registry, self.id, FakeBitcoin(bytes(32)))

    def test_upgrade_does_not_contact_untrusted_calendar(self):
        proof = DetachedTimestampFile(OpSHA256(), Timestamp(bytes.fromhex(self.registry.get(self.id)["sha256"])))
        proof.timestamp.attestations.add(PendingAttestation("http://127.0.0.1:9999/private"))
        self.registry.update(self.id, proof=serialize(proof))
        with patch("cartorio_documentos.ots.RemoteCalendar") as remote:
            upgrade(self.registry, self.id, remote_factory=remote)
            remote.assert_not_called()

    def test_lightning_invoice_recovery_and_paid_preimage(self):
        registry, record_id = self.paid_registry()
        node = FakeNode()
        invoice_for(registry, record_id, node)
        invoice_for(registry, record_id, node)
        self.assertEqual(len(node.invoices), 1)
        self.assertEqual(sync_payment(registry, record_id, node)["payload"]["payment"]["status"], "unpaid")
        node.pay()
        receipt = sync_payment(registry, record_id, node)
        self.assertEqual(receipt["payload"]["payment"]["status"], "paid")
        self.assertNotIn(node.preimage.hex(), json.dumps(receipt))
        self.assertEqual(stamp(registry, record_id, remote_factory=FakeCalendar)["payload"]["bitcoin"]["status"], "pending")

    def test_lightning_wrong_network_underpayment_and_preimage_rejected(self):
        registry, record_id = self.paid_registry()
        node = FakeNode()
        invoice_for(registry, record_id, node)
        node.network = "bitcoin"
        with self.assertRaises(RegistryError):
            sync_payment(registry, record_id, node)
        node.network = "regtest"
        node.pay()
        node.invoices[0]["amount_received_msat"] = 1
        with self.assertRaises(RegistryError):
            sync_payment(registry, record_id, node)
        node.invoices[0]["amount_received_msat"] = 2500
        node.invoices[0]["payment_preimage"] = "00" * 32
        with self.assertRaises(RegistryError):
            sync_payment(registry, record_id, node)
        self.assertEqual(registry.get(record_id)["payment_status"], "unpaid")

    def test_forwarding_report_excludes_failed_and_unsettled(self):
        node = FakeNode()
        node.forward_data = [{"status": "settled", "fee_msat": "1500msat"},
                             {"status": "failed", "fee_msat": 999999}, {"status": "offered", "fee_msat": 2000}]
        report = forwarding_report(node)
        self.assertEqual(report["settled_forwards_retained"], 1)
        self.assertEqual(report["fees_msat_retained"], 1500)

    def test_financial_and_remote_http_write_commands_are_blocked(self):
        with self.assertRaises(RegistryError):
            CoreLightning(["lightning-cli"], "bitcoin").call("pay", bolt11="any")
        with self.assertRaises(RegistryError):
            BitcoinRPC("http://remote.example:8332", "/tmp/cookie")
        with self.assertRaises(RegistryError):
            BitcoinRPC("http://127.0.0.1:8332", "/tmp/cookie").call("sendtoaddress", "addr", 1)


if __name__ == "__main__":
    unittest.main()
