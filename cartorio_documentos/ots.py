"""Provas OTS reais. Somente um Bitcoin Core sincronizado confirma a prova."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from bitcoin.core import CBlockHeader, b2lx
from opentimestamps.calendar import RemoteCalendar
from opentimestamps.core.notary import BitcoinBlockHeaderAttestation, PendingAttestation
from opentimestamps.core.op import OpAppend, OpSHA256
from opentimestamps.core.serialize import BytesDeserializationContext, BytesSerializationContext
from opentimestamps.core.timestamp import DetachedTimestampFile, Timestamp

from .registry import Registry, RegistryError, now

CALENDARS = ("https://a.pool.opentimestamps.org", "https://b.pool.opentimestamps.org")
UPGRADE_CALENDARS = {
    "https://alice.btc.calendar.opentimestamps.org", "https://bob.btc.calendar.opentimestamps.org",
    "https://finney.calendar.eternitywall.com", *CALENDARS,
}


def serialize(proof: DetachedTimestampFile) -> bytes:
    ctx = BytesSerializationContext()
    proof.serialize(ctx)
    return ctx.getbytes()


def deserialize(raw: bytes, digest: str) -> DetachedTimestampFile:
    if len(raw) > 1024 * 1024:
        raise RegistryError("Prova OTS excede 1 MiB.")
    proof = DetachedTimestampFile.deserialize(BytesDeserializationContext(raw))
    if not isinstance(proof.file_hash_op, OpSHA256) or proof.file_digest.hex() != digest:
        raise RegistryError("A prova OTS nao pertence ao SHA-256 deste documento.")
    return proof


def stamp(registry: Registry, record_id: str, *, remote_factory=RemoteCalendar) -> dict:
    row = registry.require_paid(record_id)
    if row["proof"]:
        deserialize(row["proof"], row["sha256"])
        return registry.receipt(record_id)
    proof = DetachedTimestampFile(OpSHA256(), Timestamp(bytes.fromhex(row["sha256"])))
    # O calendario recebe um compromisso com nonce, nao o arquivo ou seu hash direto.
    tip = proof.timestamp.ops.add(OpAppend(os.urandom(16))).ops.add(OpSHA256())
    accepted = 0
    for url in CALENDARS:
        try:
            response = remote_factory(url).submit(tip.msg, timeout=10)
            if not list(response.all_attestations()):
                continue
            tip.merge(response)
            accepted += 1
        except Exception:
            continue
    if not accepted:
        raise RegistryError("Nenhum calendario respondeu. Registro preservado; tente stamp novamente.")
    raw = serialize(proof)
    # A primeira prova vence uma concorrencia; uma nova tentativa nao a substitui.
    with registry.connection() as db:
        db.execute("UPDATE records SET proof = ? WHERE id = ? AND proof IS NULL", (raw, record_id))
    return registry.receipt(record_id)


def upgrade(registry: Registry, record_id: str, *, remote_factory=RemoteCalendar) -> dict:
    row = registry.require_paid(record_id)
    if not row["proof"]:
        raise RegistryError("Crie a prova com stamp primeiro.")
    proof = deserialize(row["proof"], row["sha256"])
    # URLs recebidas em provas nao podem acessar livremente a rede interna.
    for message, attestation in list(proof.timestamp.all_attestations()):
        if not isinstance(attestation, PendingAttestation):
            continue
        uri = attestation.uri
        if uri not in UPGRADE_CALENDARS:
            continue
        try:
            response = remote_factory(uri).get_timestamp(message, timeout=10)
            _merge_at(proof.timestamp, message, response)
        except Exception:
            continue
    raw = serialize(proof)
    # Impede que uma atualizacao concorrente sobrescreva prova mais recente.
    with registry.connection() as db:
        db.execute("UPDATE records SET proof = ? WHERE id = ? AND proof = ?", (raw, record_id, row["proof"]))
    return registry.receipt(record_id)


def _merge_at(timestamp: Timestamp, message: bytes, response: Timestamp) -> None:
    if timestamp.msg == message:
        timestamp.merge(response)
    for child in list(timestamp.ops.values()):
        _merge_at(child, message, response)


class BitcoinRPC:
    """Cliente somente leitura; nao usa RPC de carteira nem envia transacoes."""
    def __init__(self, url: str, cookie_file: str | Path):
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise RegistryError("RPC invalido. Informe URL sem credenciais e um arquivo cookie separado.")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise RegistryError("RPC remoto exige HTTPS; HTTP permitido somente no proprio servidor.")
        self.url, self.cookie_file = url, Path(cookie_file).expanduser()

    def call(self, method: str, *params):
        if method not in {"getblockchaininfo", "getblockhash", "getblockheader"}:
            raise RegistryError("RPC de escrita nao permitido neste modulo.")
        auth = base64.b64encode(self.cookie_file.read_bytes().strip()).decode("ascii")
        request = Request(self.url, data=json.dumps({"jsonrpc": "1.0", "id": "cartorio", "method": method,
                                                    "params": list(params)}).encode(),
                          headers={"Content-Type": "application/json", "Authorization": "Basic " + auth})
        try:
            with urlopen(request, timeout=15) as response:
                result = json.loads(response.read(1024 * 1024))
        except Exception as exc:
            raise RegistryError("Falha ao consultar Bitcoin Core. Confira disponibilidade e cookie RPC.") from exc
        if result.get("error"):
            raise RegistryError("Bitcoin Core recusou a consulta de verificacao.")
        return result["result"]


def verify_bitcoin(registry: Registry, record_id: str, rpc: BitcoinRPC, *, min_confirmations: int = 6) -> dict:
    if type(min_confirmations) is not int or min_confirmations < 1:
        raise RegistryError("Numero minimo de confirmacoes invalido.")
    row = registry.require_paid(record_id)
    # Nunca conservar um resultado positivo antigo depois de uma nova tentativa falha.
    registry.update(record_id, bitcoin_verification=None)
    if not row["proof"]:
        raise RegistryError("Registro ainda sem prova OTS.")
    proof = deserialize(row["proof"], row["sha256"])
    info = rpc.call("getblockchaininfo")
    if info.get("chain") != "main" or info.get("initialblockdownload", True):
        raise RegistryError("A verificacao publica exige Bitcoin Core mainnet sincronizado; regtest nao confirma prova real.")
    for message, attestation in proof.timestamp.all_attestations():
        if not isinstance(attestation, BitcoinBlockHeaderAttestation):
            continue
        confirmations = info["blocks"] - attestation.height + 1
        if confirmations < min_confirmations:
            continue
        block_hash = rpc.call("getblockhash", attestation.height)
        header = CBlockHeader.deserialize(bytes.fromhex(rpc.call("getblockheader", block_hash, False)))
        if b2lx(header.GetHash()) != block_hash:
            continue
        try:
            block_time = attestation.verify_against_blockheader(message, header)
        except Exception:
            continue
        if rpc.call("getblockhash", attestation.height) != block_hash:
            raise RegistryError("Mudanca da cadeia durante verificacao. Tente novamente.")
        verification = {"network": "bitcoin-mainnet", "height": attestation.height,
                        "block_hash": block_hash, "block_time": block_time,
                        "confirmations_at_check": confirmations, "checked_at_server": now()}
        registry.update(record_id, bitcoin_verification=json.dumps(verification))
        return registry.receipt(record_id)
    raise RegistryError("Prova ainda nao verificavel com as confirmacoes exigidas. Execute upgrade e confira o Bitcoin Core.")
