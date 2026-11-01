"""Impede o teste automatico de usar uma rede com valor real."""
import importlib.util
import sys
import unittest
from pathlib import Path

LAB = Path(__file__).resolve().parent.parent / "laboratorio-lightning"
sys.path.insert(0, str(LAB))
spec = importlib.util.spec_from_file_location("teste_documentos", LAB / "teste_documentos.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class LabGuardTest(unittest.TestCase):
    def test_accepts_only_all_three_regtest_nodes(self):
        module.assert_regtest({"chain": "regtest"}, {name: {"network": "regtest"} for name in "abc"})

    def test_rejects_mainnet_bitcoin_and_any_non_regtest_lightning_node(self):
        nodes = {name: {"network": "regtest"} for name in "abc"}
        with self.assertRaises(RuntimeError):
            module.assert_regtest({"chain": "main"}, nodes)
        for name in "abc":
            modified = {key: {"network": "bitcoin" if key == name else "regtest"} for key in "abc"}
            with self.subTest(node=name), self.assertRaises(RuntimeError):
                module.assert_regtest({"chain": "regtest"}, modified)

    def test_rejects_missing_node_or_unknown_chain(self):
        with self.assertRaises(RuntimeError):
            module.assert_regtest({"chain": "regtest"}, {"a": {"network": "regtest"}})
        with self.assertRaises(RuntimeError):
            module.assert_regtest({}, {name: {"network": "regtest"} for name in "abc"})
