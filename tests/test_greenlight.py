"""Greenlight adapter tests with fake SDK; never contact Bitcoin or Blockstream."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from cartorio_documentos.greenlight import GreenlightStatus
from cartorio_documentos.registry import RegistryError
from cartorio_documentos.security import atomic_private

ID = "02" + ("ab" * 32)
WRONG = "03" + ("cd" * 32)


class FakeCredentials:
    @staticmethod
    def from_bytes(raw):
        if raw != b"private-synthetic-credentials":
            raise ValueError("bad credentials")
        return object()


class SDK:
    Credentials = FakeCredentials
    response = SimpleNamespace(id=bytes.fromhex(ID), network="bitcoin")
    called = False

    class Scheduler:
        def __init__(self, network, credentials):
            if network not in ("bitcoin", "testnet") or credentials is None:
                raise AssertionError("invalid SDK call")

        def node(self):
            SDK.called = True
            return SimpleNamespace(get_info=lambda: SDK.response)


class GreenlightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "device.gfs"
        atomic_private(self.path, b"private-synthetic-credentials")
        SDK.response = SimpleNamespace(id=bytes.fromhex(ID), network="bitcoin")
        SDK.called = False

    def tearDown(self):
        self.tmp.cleanup()

    def inspect(self, **changes):
        return GreenlightStatus(self.path, ID, sdk=SDK, **changes).check()

    def test_connects_with_official_scheduler_interface_and_matches_node(self):
        result = self.inspect()
        self.assertTrue(SDK.called)
        self.assertEqual(result["node_id"], ID)
        self.assertEqual(result["network"], "bitcoin")
        self.assertFalse(result["mainnet_invoices_enabled"])
        self.assertNotIn("private-synthetic", str(result))

    def test_wrong_node_id_fails_closed(self):
        SDK.response = SimpleNamespace(id=bytes.fromhex(WRONG), network="bitcoin")
        with self.assertRaisesRegex(RegistryError, "diferente"):
            self.inspect()

    def test_wrong_network_fails_closed(self):
        SDK.response = SimpleNamespace(id=bytes.fromhex(ID), network="testnet")
        with self.assertRaisesRegex(RegistryError, "rede diferente"):
            self.inspect()

    def test_unsupported_network_or_bad_node_refused_before_sdk(self):
        for network in ("regtest", "signet", ""):
            with self.subTest(network=network), self.assertRaises(RegistryError):
                GreenlightStatus(self.path, ID, network=network, sdk=SDK)
        with self.assertRaises(RegistryError):
            GreenlightStatus(self.path, "bad", sdk=SDK)
        self.assertFalse(SDK.called)

    def test_missing_or_insecure_credentials_never_reach_sdk(self):
        self.path.chmod(0o644)
        with self.assertRaises(RegistryError):
            self.inspect()
        self.assertFalse(SDK.called)
        self.path.unlink()
        with self.assertRaises(OSError):
            self.inspect()
        self.assertFalse(SDK.called)

    def test_opaque_binary_credentials_are_not_trimmed(self):
        original = b"\\x20private-synthetic-credentials\\n"
        atomic_private(self.path, original)

        class ExactCredentials:
            @staticmethod
            def from_bytes(value):
                self.assertEqual(value, original)
                return object()

        class ExactSdk(SDK):
            Credentials = ExactCredentials

        result = GreenlightStatus(self.path, ID, sdk=ExactSdk).check()
        self.assertTrue(result["authenticated_identity"])

    def test_provider_error_redacted(self):
        SDK.response = object()
        with self.assertRaises(RegistryError):
            self.inspect()

    def test_invoice_and_wallet_methods_are_refused(self):
        instance = GreenlightStatus(self.path, ID, sdk=SDK)
        for command in ("invoice", "pay", "withdraw", "fundchannel", "listinvoices"):
            with self.subTest(command=command), self.assertRaises(RegistryError):
                instance.call(command)
        self.assertFalse(SDK.called)


if __name__ == "__main__":
    unittest.main()
