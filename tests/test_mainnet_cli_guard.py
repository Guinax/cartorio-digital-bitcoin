"""Mainnet must always use the guarded production configuration."""
import tempfile
import unittest
from pathlib import Path

from cartorio_documentos.__main__ import parser, run
from cartorio_documentos.registry import RegistryError


class MainnetCliGuardTests(unittest.TestCase):
    def test_legacy_network_bitcoin_rejected_for_every_financial_entrypoint(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / "state"
            document = Path(directory) / "synthetic.txt"
            document.write_text("synthetic document")
            commands = [["init"], ["register", str(document)], ["invoice", "ID"],
                        ["sync-payment", "ID"], ["work", "--once"]]
            for command in commands:
                with self.subTest(command=command):
                    args = parser().parse_args(["--network", "bitcoin", "--data", str(data), *command])
                    with self.assertRaisesRegex(RegistryError, "Mainnet exige --config"):
                        run(args)
            self.assertFalse(data.exists(), "Blocked operations must not initialize data")

    def test_regtest_cli_stays_usable_for_lab(self):
        with tempfile.TemporaryDirectory() as directory:
            args = parser().parse_args(["--network", "regtest", "--data", str(Path(directory) / "state"), "init"])
            result = run(args)
            self.assertIn("issuer_key_sha256", result)


if __name__ == "__main__":
    unittest.main()
