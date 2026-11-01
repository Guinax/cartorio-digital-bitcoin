"""Safe smoke tests for the no-card Linux preparation script.

These tests NEVER execute its root-only --preparar-base mode.
"""
from pathlib import Path
import subprocess
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "sem-cartao" / "preparar-servidor.sh"


class SafeLinuxSetupScriptTests(unittest.TestCase):
    def test_bash_syntax(self):
        result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_diagnostics_are_read_only_and_available(self):
        result = subprocess.run(["bash", str(SCRIPT), "--diagnostico"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Disco do sistema", result.stdout)
        self.assertIn("Este comando nao testa", result.stdout)

    def test_help_does_not_prepare_host(self):
        result = subprocess.run(["bash", str(SCRIPT), "--help"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--preparar-base", result.stdout)

    def test_unknown_argument_fails_closed(self):
        result = subprocess.run(["bash", str(SCRIPT), "--fund-wallet"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
