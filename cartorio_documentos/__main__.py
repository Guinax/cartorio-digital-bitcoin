"""Interface local do operador: python3 -m cartorio_documentos --help."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .registry import Registry, RegistryError, verify_receipt


def lightning_node(args, *, forwarding=False):
    from .lightning import CoreLightning
    if args.lab:
        if args.network != "regtest":
            raise RegistryError("--lab funciona somente com --network regtest.")
        compose = Path(__file__).resolve().parent.parent / "laboratorio-lightning" / "compose.yaml"
        command = ["docker", "compose", "-f", str(compose), "exec", "-T",
                   "lightning-b" if forwarding else "lightning-c", "lightning-cli", "--network=regtest"]
    else:
        raw = os.environ.get("CARTORIO_LIGHTNING_COMMAND")
        if not raw:
            raise RegistryError("Informe --lab ou configure CARTORIO_LIGHTNING_COMMAND (lista JSON).")
        command = json.loads(raw)
        if not isinstance(command, list):
            raise RegistryError("CARTORIO_LIGHTNING_COMMAND precisa ser uma lista JSON.")
    return CoreLightning(command, args.network)


def parser():
    root = argparse.ArgumentParser(description="Registro de integridade e provas Bitcoin. Nao autoriza transferencias da rede.")
    root.add_argument("--data", default=os.environ.get("CARTORIO_DATA_DIR", ".cartorio-documentos"))
    root.add_argument("--fee-msat", type=int, default=int(os.environ.get("CARTORIO_FEE_MSAT", "0")),
                      help="Tarifa dos NOVOS registros; zero por padrao. 1000 msat = 1 satoshi.")
    root.add_argument("--network", choices=["regtest", "bitcoin", "testnet", "signet"], default="regtest",
                      help="Rede de COBRANCA Lightning; as provas OTS publicas sempre usam Bitcoin mainnet.")
    commands = root.add_subparsers(dest="action", required=True)
    commands.add_parser("init", help="Inicializa banco e chave local sem substituir chave existente.")
    create = commands.add_parser("register", help="Calcula SHA-256 localmente e emite comprovante assinado.")
    create.add_argument("file", type=Path)
    for name in ("receipt", "stamp", "upgrade", "export-proof", "invoice", "sync-payment", "verify-bitcoin"):
        sub = commands.add_parser(name)
        sub.add_argument("record_id")
        if name in {"invoice", "sync-payment"}:
            sub.add_argument("--lab", action="store_true", help="Usa o no C do laboratorio regtest existente.")
        if name == "export-proof":
            sub.add_argument("--out", required=True, type=Path)
        if name == "verify-bitcoin":
            sub.add_argument("--rpc-url", default="http://127.0.0.1:8332")
            sub.add_argument("--cookie", required=True, type=Path)
            sub.add_argument("--confirmations", type=int, default=6)
    check = commands.add_parser("verify-receipt", help="Confere assinatura e arquivo; nao confirma a blockchain.")
    check.add_argument("file", type=Path)
    check.add_argument("--receipt", required=True, type=Path)
    check.add_argument("--public-key", required=True, type=Path, help="Chave confiavel do emissor, obtida separadamente.")
    report = commands.add_parser("forwards", help="Consulta somente taxas liquidadas do proprio no.")
    report.add_argument("--lab", action="store_true", help="Consulta o no B do laboratorio regtest.")
    return root


def run(args):
    registry = Registry(args.data, fee_msat=args.fee_msat, network=args.network)
    if args.action == "init":
        return registry.initialize()
    if args.action == "register":
        return registry.register(args.file)
    if args.action == "receipt":
        return registry.receipt(args.record_id)
    if args.action == "verify-receipt":
        return verify_receipt(json.loads(args.receipt.read_text(encoding="utf-8")), args.file,
                              args.public_key.read_bytes())
    if args.action in {"stamp", "upgrade"}:
        from . import ots
        return getattr(ots, args.action)(registry, args.record_id)
    if args.action == "export-proof":
        from .ots import deserialize
        row = registry.get(args.record_id)
        if not row["proof"]:
            raise RegistryError("Registro ainda sem prova OTS.")
        deserialize(row["proof"], row["sha256"])
        with args.out.open("xb") as target:
            target.write(row["proof"])
        return {"proof_file": str(args.out), "document_sha256": row["sha256"]}
    if args.action == "verify-bitcoin":
        from .ots import BitcoinRPC, verify_bitcoin
        return verify_bitcoin(registry, args.record_id, BitcoinRPC(args.rpc_url, args.cookie),
                              min_confirmations=args.confirmations)
    if args.action in {"invoice", "sync-payment", "forwards"}:
        from .lightning import forwarding_report, invoice_for, sync_payment
        node = lightning_node(args, forwarding=args.action == "forwards")
        if args.action == "forwards":
            return forwarding_report(node)
        return (invoice_for if args.action == "invoice" else sync_payment)(registry, args.record_id, node)
    raise RegistryError("Comando desconhecido.")


def main():
    try:
        result = run(parser().parse_args())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (RegistryError, OSError, ValueError, KeyError, ImportError) as exc:
        if isinstance(exc, ImportError):
            message = "Dependencias ausentes. Execute: python3 -m pip install -r requirements-documentos.txt"
        else:
            message = str(exc)
        print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
