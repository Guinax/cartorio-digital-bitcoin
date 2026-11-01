"""Interface local do operador: python3 -m cartorio_documentos --help."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .registry import Registry, RegistryError, verify_receipt


def lightning_node(args, *, forwarding=False):
    if getattr(args, "config_data", None):
        from .production import node_for
        return node_for(args.config_data, args.registry)
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
    root.add_argument("--config", type=Path, help="Perfil de producao JSON; prevalece sobre opcoes do laboratorio.")
    root.add_argument("--key-password-file", type=Path, help="Arquivo privado para criptografia da chave do emissor.")
    root.add_argument("--fee-msat", type=int, default=int(os.environ.get("CARTORIO_FEE_MSAT", "0")),
                      help="Tarifa dos NOVOS registros; zero por padrao. 1000 msat = 1 satoshi.")
    root.add_argument("--network", choices=["regtest", "bitcoin", "testnet", "signet"], default="regtest",
                      help="Rede de COBRANCA Lightning; as provas OTS publicas sempre usam Bitcoin mainnet.")
    commands = root.add_subparsers(dest="action", required=True)
    commands.add_parser("init", help="Inicializa banco e chave local sem substituir chave existente.")
    commands.add_parser("protect-key", help="Criptografa a chave existente preservando a identidade do emissor.")
    commands.add_parser("doctor", help="Diagnostico mainnet somente leitura; exige --config.")
    commands.add_parser("backup", help="Backup autenticado e criptografado; exige --config.")
    restore = commands.add_parser("restore", help="Restaura em diretorio novo; exige --config.")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--destination", required=True, type=Path)
    restore.add_argument("--issuer-fingerprint", required=True)
    worker = commands.add_parser("work", help="Atualiza provas e reconcilia pagamentos; exige --config.")
    worker.add_argument("--once", action="store_true")
    backup_key = commands.add_parser("create-backup-key", help="Gera chave de backup em arquivo privado exclusivo.")
    backup_key.add_argument("--out", required=True, type=Path)
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
            sub.add_argument("--cookie", type=Path)
            sub.add_argument("--confirmations", type=int, default=6)
    check = commands.add_parser("verify-receipt", help="Confere assinatura e arquivo; nao confirma a blockchain.")
    check.add_argument("file", type=Path)
    check.add_argument("--receipt", required=True, type=Path)
    check.add_argument("--public-key", required=True, type=Path, help="Chave confiavel do emissor, obtida separadamente.")
    report = commands.add_parser("forwards", help="Consulta somente taxas liquidadas do proprio no.")
    report.add_argument("--lab", action="store_true", help="Consulta o no B do laboratorio regtest.")
    return root


def run(args):
    if args.config:
        from .production import load_config, registry_for
        args.config_data = load_config(args.config)
        if getattr(args, "lab", False):
            raise RegistryError("Perfil mainnet nao permite --lab.")
        registry = registry_for(args.config_data)
        args.network = "bitcoin"
        args.registry = registry
    else:
        from .security import private_read
        password = private_read(args.key_password_file) if args.key_password_file else None
        registry = Registry(args.data, fee_msat=args.fee_msat, network=args.network, password=password)
    if args.action in {"doctor", "backup", "restore", "work"} and not args.config:
        raise RegistryError("Este comando exige --config apontando para o perfil de producao.")
    if args.action == "protect-key":
        return registry.protect_key()
    if args.action == "create-backup-key":
        from cryptography.fernet import Fernet
        fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as target:
            target.write(Fernet.generate_key() + b"\n")
            target.flush()
            os.fsync(target.fileno())
        return {"created": True, "path": str(args.out), "notice": "Guarde esta chave fora do servidor e separada dos backups."}
    if args.action == "doctor":
        from .production import doctor
        return doctor(args.config_data, registry)
    if args.action == "backup":
        from .backup import create_backup
        return create_backup(registry, args.config_data["backup_dir"], args.config_data["backup_key_file"])
    if args.action == "restore":
        from .backup import restore_backup
        return restore_backup(args.archive, args.destination, args.config_data["backup_key_file"],
                              registry.password, args.issuer_fingerprint)
    if args.action == "work":
        from .worker import work
        return work(args.config_data, registry, once=args.once)
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
        if args.config:
            from .production import bitcoin_for
            from .ots import verify_bitcoin
            return verify_bitcoin(registry, args.record_id, bitcoin_for(args.config_data),
                                  min_confirmations=args.config_data["min_confirmations"])
        from .ots import BitcoinRPC, verify_bitcoin
        if not args.cookie:
            raise RegistryError("Informe --cookie ou use o perfil --config.")
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
        if isinstance(result, dict) and "ready_for_receiving" in result and not result["ready_for_receiving"]:
            return 2
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
