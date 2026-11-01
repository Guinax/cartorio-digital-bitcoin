"""Read-only host preflight for Cartorio Bitcoin mainnet.

Does not read wallet keys, access RPC, make payments, or change the host.
Network/protocol checks are delegated to the production 'doctor'.
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
from pathlib import Path

GIB = 1024 ** 3


def check(name: str, okay: bool, detail: str) -> dict:
    return {"name": name, "ok": bool(okay), "detail": detail}


def run(data_path: Path, *, min_volume_gib: int = 1500, min_ram_gib: int = 8,
        min_free_gib: int = 100, sys_root: Path = Path("/")) -> dict:
    results = []
    results.append(check("linux_host", platform.system() == "Linux", platform.system()))
    memory = sys_root / "proc/meminfo"
    try:
        lines = memory.read_text().splitlines()
        ram_kib = int(next(s.split()[1] for s in lines if s.startswith("MemTotal:")))
        ram_gib = ram_kib / 1024 ** 2
        results.append(check("physical_ram", ram_gib >= min_ram_gib,
                             f"{ram_gib:.1f} GiB RAM (required {min_ram_gib} GiB)"))
    except (OSError, ValueError, StopIteration):
        results.append(check("physical_ram", False, "Cannot read RAM capacity"))
    try:
        if data_path.is_symlink() or not data_path.is_dir():
            raise ValueError("Data directory must exist and must not be a symlink")
        disk = shutil.disk_usage(data_path)
        volume_gib = disk.total / GIB
        free_gib = disk.free / GIB
        results.append(check("durable_data_volume", volume_gib >= min_volume_gib,
                             f"{volume_gib:.0f} GiB capacity (recommended {min_volume_gib} GiB)"))
        results.append(check("free_disk_space", free_gib >= min_free_gib,
                             f"{free_gib:.0f} GiB free (minimum {min_free_gib} GiB)"))
    except (OSError, ValueError) as exc:
        results.append(check("durable_data_volume", False, str(exc)))
        results.append(check("free_disk_space", False, "Cannot check disk space"))
    for binary in ("bitcoind", "bitcoin-cli", "lightningd", "lightning-cli"):
        available = bool(shutil.which(binary))
        results.append(check("binary_" + binary.replace("-", "_"), available,
                             "Found in PATH" if available else "Not installed or not in PATH"))
    return {"schema": "cartorio-mainnet-preflight/v1",
            "ready_for_host_setup": all(x["ok"] for x in results),
            "checks": results,
            "note": "Host-only checks; NOT permission to charge BTC. Run cartorio_documentos doctor separately."}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only host preflight (never connects to wallets)")
    parser.add_argument("--data-dir", type=Path, default=Path("/var/lib/bitcoind"))
    parser.add_argument("--min-volume-gib", type=int, default=1500)
    parser.add_argument("--min-ram-gib", type=int, default=8)
    parser.add_argument("--min-free-gib", type=int, default=100)
    args = parser.parse_args(argv)
    if min(args.min_volume_gib, args.min_ram_gib, args.min_free_gib) < 1:
        parser.error("Minimum capacities must be positive")
    result = run(args.data_dir, min_volume_gib=args.min_volume_gib,
                 min_ram_gib=args.min_ram_gib, min_free_gib=args.min_free_gib)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ready_for_host_setup"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
