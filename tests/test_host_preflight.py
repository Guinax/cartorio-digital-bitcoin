"""Unit tests for read-only production-host checks, no real nodes."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

FILE = Path(__file__).resolve().parent.parent / "deploy/mainnet/host_preflight.py"
spec = importlib.util.spec_from_file_location("host_preflight", FILE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HostPreflightTests(unittest.TestCase):
    def test_fails_closed_without_tools_or_storage(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "proc").mkdir()
            (root / "proc/meminfo").write_text("MemTotal: 4096000 kB\n")
            with patch.object(module.platform, "system", return_value="Linux"), \
                    patch.object(module.shutil, "which", return_value=None):
                result = module.run(root, sys_root=root)
            self.assertFalse(result["ready_for_host_setup"])
            self.assertFalse(next(x for x in result["checks"] if x["name"] == "physical_ram")["ok"])
            self.assertFalse(next(x for x in result["checks"] if x["name"] == "binary_bitcoind")["ok"])

    def test_all_checks_pass_with_synthetic_host(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "proc").mkdir()
            (root / "proc/meminfo").write_text("MemTotal: 16777216 kB\n")
            disk = type("Disk", (), {"total": 2000 * module.GIB, "free": 500 * module.GIB})()
            with patch.object(module.platform, "system", return_value="Linux"), \
                    patch.object(module.shutil, "which", return_value="/usr/bin/fake"), \
                    patch.object(module.shutil, "disk_usage", return_value=disk):
                result = module.run(root, sys_root=root)
            self.assertTrue(result["ready_for_host_setup"])

    def test_oracle_free_tier_pruned_volume_can_pass_explicit_limits(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "proc").mkdir()
            (root / "proc/meminfo").write_text("MemTotal: 12582912 kB\\n")
            disk = type("Disk", (), {"total": 150 * 10**9, "free": 80 * 10**9})()
            with patch.object(module.platform, "system", return_value="Linux"), \\
                    patch.object(module.shutil, "which", return_value="/usr/bin/fake"), \\
                    patch.object(module.shutil, "disk_usage", return_value=disk):
                archive = module.run(root, sys_root=root)
                pruned = module.run(root, sys_root=root, min_volume_gib=120,
                                    min_free_gib=35, min_ram_gib=8)
            self.assertFalse(archive["ready_for_host_setup"])
            self.assertTrue(pruned["ready_for_host_setup"])

    def test_missing_directory_fails_without_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "proc").mkdir()
            (root / "proc/meminfo").write_text("MemTotal: 16777216 kB\n")
            with patch.object(module.shutil, "which", return_value="/usr/bin/fake"):
                result = module.run(root / "nonexistent", sys_root=root)
            self.assertFalse(result["ready_for_host_setup"])
            self.assertFalse(next(x for x in result["checks"] if x["name"] == "durable_data_volume")["ok"])


if __name__ == "__main__":
    unittest.main()
