"""Configuracao e diagnostico do perfil mainnet. Nunca movimenta fundos."""
import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path

from .backup import decode_archive
from .lightning import CoreLightningREST, msat
from .ots import BitcoinRPC
from .registry import Registry, RegistryError, fingerprint, now
from .security import private_read

MAINNET_GENESIS = "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"
PATHS = {"data_dir", "key_password_file", "backup_dir", "backup_key_file", "bitcoin_cookie_file",
         "lightning_rune_file", "lightning_ca_file"}
DEFAULTS = {"schema": 1, "allow_mainnet_invoices": False, "service_fee_msat": 0,
            "max_invoice_msat": 10_000_000, "min_confirmations": 6, "worker_interval_seconds": 300,
            "backup_interval_seconds": 21600, "max_records_per_cycle": 25, "max_tip_age_seconds": 10800}


def load_config(path) -> dict:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    allowed = set(DEFAULTS) | PATHS | {"bitcoin_rpc_url", "lightning_rest_url", "lightning_node_id"}
    if not isinstance(raw, dict) or set(raw) - allowed:
        raise RegistryError("Configuracao invalida ou com campos desconhecidos.")
    config = {**DEFAULTS, **raw}
    if config["schema"] != 1 or type(config["allow_mainnet_invoices"]) is not bool:
        raise RegistryError("Schema ou chave allow_mainnet_invoices invalidos.")
    for name in PATHS:
        if not isinstance(config.get(name), str) or not Path(config[name]).is_absolute():
            raise RegistryError(f"Configure um caminho absoluto para {name}.")
        config[name] = Path(config[name])
    for name in ("bitcoin_rpc_url", "lightning_rest_url"):
        if not isinstance(config.get(name), str):
            raise RegistryError(f"Configure {name}.")
    if not re.fullmatch(r"0[23][0-9a-f]{64}", config.get("lightning_node_id", "")):
        raise RegistryError("Configure lightning_node_id com a chave publica real esperada do no.")
    bounds = {"service_fee_msat": (0, 2_100_000_000_000_000_000), "max_invoice_msat": (1, 2_100_000_000_000_000_000),
              "min_confirmations": (6, 1008), "worker_interval_seconds": (60, 3600),
              "backup_interval_seconds": (3600, 86400), "max_records_per_cycle": (1, 1000),
              "max_tip_age_seconds": (3600, 86400)}
    for name, (low, high) in bounds.items():
        if type(config[name]) is not int or not low <= config[name] <= high:
            raise RegistryError(f"Valor fora do intervalo permitido: {name}.")
    if config["service_fee_msat"] > config["max_invoice_msat"]:
        raise RegistryError("Tarifa maior que o limite maximo de fatura.")
    if config["backup_dir"].resolve().is_relative_to(config["data_dir"].resolve()):
        raise RegistryError("Backup deve ficar fora do diretorio de dados.")
    return config


def registry_for(config) -> Registry:
    password = private_read(config["key_password_file"])
    if len(password) < 16:
        raise RegistryError("A senha da chave exige pelo menos 16 bytes.")
    return Registry(config["data_dir"], network="bitcoin", fee_msat=config["service_fee_msat"],
                    password=password, require_encrypted_key=True)


def bitcoin_for(config):
    return BitcoinRPC(config["bitcoin_rpc_url"], config["bitcoin_cookie_file"])


def node_for(config, registry):
    node = CoreLightningREST(config["lightning_rest_url"], config["lightning_rune_file"], config["lightning_ca_file"],
                             node_id=config["lightning_node_id"])
    def gate(amount):
        if not config["allow_mainnet_invoices"]:
            raise RegistryError("Criacao de faturas mainnet esta pausada na configuracao.")
        if not 0 < amount <= config["max_invoice_msat"]:
            raise RegistryError("Valor da fatura fora do limite configurado.")
        result = doctor(config, registry, node=node, required_msat=amount)
        if not result["ready_for_receiving"]:
            failures = [item["name"] for item in result["checks"] if not item["ok"]]
            raise RegistryError("Fatura bloqueada pelo diagnostico: " + ", ".join(failures))
    node.invoice_gate = gate
    return node


def doctor(config, registry, *, rpc=None, node=None, required_msat=None, clock=None) -> dict:
    clock = time.time() if clock is None else clock
    checks = []
    info = None
    def check(name, fn):
        try:
            detail = fn()
            checks.append({"name": name, "ok": True, "detail": detail})
            return detail
        except Exception:
            checks.append({"name": name, "ok": False, "detail": "Recurso ausente, invalido ou indisponivel; confira a configuracao local."})
            return None

    def storage():
        key = registry.key()
        for path in (registry.directory, registry.key_path, registry.db_path):
            if path.stat().st_mode & 0o077:
                raise RegistryError("Permissoes de dados muito amplas.")
        private_read(config["key_password_file"])
        private_read(config["backup_key_file"])
        private_read(config["lightning_rune_file"])
        cookie = config["bitcoin_cookie_file"]
        if cookie.is_symlink() or not cookie.is_file() or cookie.stat().st_mode & 0o027:
            raise RegistryError("Cookie RPC exige permissoes privadas ou grupo confiavel sem escrita.")
        with registry.connection() as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RegistryError("Banco inconsistente.")
            if db.execute("SELECT 1 FROM records WHERE network != 'bitcoin' LIMIT 1").fetchone():
                raise RegistryError("Perfil mainnet exige banco separado dos registros de laboratorio.")
        return {"encrypted_key": True, "issuer_key_sha256": fingerprint(key.public_key())}
    check("storage_and_secrets", storage)

    def backup():
        status = json.loads((registry.directory / "backup-status.json").read_text())
        age = clock - datetime.fromisoformat(status["created_at"]).timestamp()
        if not 0 <= age <= config["backup_interval_seconds"] * 2:
            raise RegistryError("Backup ausente ou antigo.")
        archive = Path(status["path"]).resolve()
        if not archive.is_relative_to(config["backup_dir"].resolve()):
            raise RegistryError("Backup fora do diretorio configurado.")
        if archive.stat().st_size > 128 * 1024 * 1024:
            raise RegistryError("Backup excessivamente grande.")
        if hashlib.sha256(archive.read_bytes()).hexdigest() != status["sha256"]:
            raise RegistryError("Backup alterado.")
        payload = decode_archive(archive, config["backup_key_file"])
        if payload["issuer_key_sha256"] != fingerprint(registry.key().public_key()):
            raise RegistryError("Backup de outro emissor.")
        return {"age_seconds": int(age), "authenticated_archive": True}
    check("recent_encrypted_backup", backup)

    def heartbeat():
        status = json.loads((registry.directory / "worker-status.json").read_text())
        age = clock - datetime.fromisoformat(status["checked_at"]).timestamp()
        if status.get("network") != "bitcoin" or not 0 <= age <= config["worker_interval_seconds"] * 2:
            raise RegistryError("Worker nao iniciou ou seu sinal de atividade esta antigo.")
        with registry.connection() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='processing_jobs'").fetchone():
                if db.execute("SELECT 1 FROM processing_jobs WHERE failures > 0 LIMIT 1").fetchone():
                    raise RegistryError("A fila possui falhas ainda nao resolvidas. Novas faturas ficam pausadas.")
        return {"age_seconds": int(age)}
    check("worker_heartbeat", heartbeat)

    def bitcoin():
        nonlocal rpc, info
        rpc = rpc or bitcoin_for(config)
        info = rpc.call("getblockchaininfo")
        if (info.get("chain") != "main" or info.get("initialblockdownload", True)
                or type(info.get("blocks")) is not int or type(info.get("headers")) is not int
                or not 0 <= info["headers"] - info["blocks"] <= 2
                or not -7200 <= clock - info.get("time", 0) <= config["max_tip_age_seconds"]
                or rpc.call("getblockhash", 0) != MAINNET_GENESIS):
            raise RegistryError("Bitcoin mainnet nao esta sincronizado ou ponta esta antiga.")
        return {"network": "main", "height": info["blocks"]}
    check("bitcoin_mainnet_synced", bitcoin)

    def lightning():
        client = node or node_for(config, registry)
        data = client.call("getinfo")
        if (data.get("network") != "bitcoin" or data.get("id") != config["lightning_node_id"]
                or data.get("warning_bitcoind_sync") or data.get("warning_lightningd_sync")
                or info is None or abs(data.get("blockheight", -100) - info["blocks"]) > 2):
            raise RegistryError("Lightning errado ou nao sincronizado.")
        channels = client.call("listpeerchannels").get("channels", [])
        inbound = sum(msat(row.get("receivable_msat", 0)) for row in channels
                      if row.get("state") == "CHANNELD_NORMAL" and row.get("peer_connected") is True
                      and not row.get("lost_state", False))
        needed = max(1, config["service_fee_msat"] if required_msat is None else required_msat)
        if inbound < needed:
            raise RegistryError("Sem capacidade de recebimento estimada suficiente.")
        return {"network": "bitcoin", "estimated_receivable_msat": inbound}
    check("lightning_identity_sync_and_inbound", lightning)
    ready = all(item["ok"] for item in checks)
    return {"checked_at": now(), "ready_for_receiving": ready,
            "mainnet_invoices_enabled": config["allow_mainnet_invoices"], "checks": checks,
            "notice": "Diagnostico nao envia pagamentos, nao abre canais e nao garante liquidez futura."}
