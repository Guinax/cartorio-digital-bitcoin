"""Registro local. O arquivo original nunca e copiado para o banco."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


class RegistryError(ValueError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def hash_file(path: str | Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def public_pem(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


def fingerprint(key: Ed25519PublicKey) -> str:
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()


def verify_receipt(receipt: dict, file: str | Path, trusted_public_key: bytes) -> dict:
    """A chave de confianca deve ser obtida do emissor por um canal confiavel."""
    try:
        key = serialization.load_pem_public_key(trusted_public_key)
        if not isinstance(key, Ed25519PublicKey):
            raise RegistryError("A chave de confianca precisa ser Ed25519.")
        payload = receipt["payload"]
        if payload["schema"] != "cartorio-documentos/v1":
            raise RegistryError("Formato de comprovante desconhecido.")
        if payload["issuer_key_sha256"] != fingerprint(key):
            raise RegistryError("O comprovante nao pertence ao emissor confiavel.")
        key.verify(base64.b64decode(receipt["signature_ed25519"], validate=True), canonical(payload))
        digest, size = hash_file(file)
        if digest != payload["document"]["sha256"] or size != payload["document"]["size_bytes"]:
            raise RegistryError("O documento nao corresponde ao comprovante: arquivo alterado ou incorreto.")
        return {
            "signature_valid": True, "document_matches": True,
            "record_id": payload["record_id"],
            "bitcoin_proof_verified_now": False,
            "notice": "Assinatura e integridade conferidas. A prova Bitcoin exige verificacao independente do .ots.",
        }
    except (InvalidSignature, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, RegistryError):
            raise
        raise RegistryError("Comprovante ou assinatura invalida.") from exc


class Registry:
    def __init__(self, directory: str | Path, *, fee_msat: int = 0, network: str = "regtest"):
        if type(fee_msat) is not int or fee_msat < 0:
            raise RegistryError("A tarifa deve ser um inteiro nao negativo em msat.")
        if network not in {"regtest", "bitcoin", "testnet", "signet"}:
            raise RegistryError("Rede Lightning desconhecida.")
        self.directory = Path(directory).expanduser().resolve()
        self.db_path = self.directory / "registry.sqlite3"
        self.key_path = self.directory / "issuer-private.pem"
        self.fee_msat, self.network = fee_msat, network

    def initialize(self) -> dict:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.key_path.exists():
            if self.db_path.exists() and self.db_path.stat().st_size:
                raise RegistryError("Banco existente sem chave. Restaure a chave original; nao gere outra por cima.")
            key = Ed25519PrivateKey.generate()
            raw = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
            fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as target:
                target.write(raw)
                target.flush()
                os.fsync(target.fileno())
        key = self.key()
        if not self.db_path.exists():
            fd = os.open(self.db_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        with self.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS records (
                id TEXT PRIMARY KEY, sha256 TEXT UNIQUE NOT NULL, size_bytes INTEGER NOT NULL,
                registered_at TEXT NOT NULL, issuer_key_sha256 TEXT NOT NULL,
                fee_msat INTEGER NOT NULL, network TEXT NOT NULL,
                payment_status TEXT NOT NULL, invoice TEXT, payment_hash TEXT, expires_at INTEGER,
                paid_at INTEGER, proof BLOB, bitcoin_verification TEXT
            )""")
            mismatched = db.execute("SELECT 1 FROM records WHERE issuer_key_sha256 != ? LIMIT 1",
                                    (fingerprint(key.public_key()),)).fetchone()
            if mismatched:
                raise RegistryError("Chave diferente da usada nos registros. Restaure a chave original.")
        pub_path = self.directory / "issuer-public.pem"
        pub_path.write_bytes(public_pem(key.public_key()))
        return {"issuer_key_sha256": fingerprint(key.public_key()), "public_key": str(pub_path)}

    def key(self) -> Ed25519PrivateKey:
        if not self.key_path.exists():
            raise RegistryError("Registro nao inicializado. Execute init primeiro.")
        key = serialization.load_pem_private_key(self.key_path.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise RegistryError("A chave do emissor precisa ser Ed25519.")
        return key

    @contextmanager
    def connection(self):
        if not self.key_path.exists() or not self.db_path.exists():
            raise RegistryError("Registro nao inicializado. Execute init primeiro.")
        db = sqlite3.connect(self.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def register(self, file: str | Path) -> dict:
        digest, size = hash_file(file)
        with self.connection() as db:
            db.execute("""INSERT INTO records
                (id, sha256, size_bytes, registered_at, issuer_key_sha256, fee_msat, network, payment_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(sha256) DO NOTHING""",
                (str(uuid.uuid4()), digest, size, now(), fingerprint(self.key().public_key()),
                 self.fee_msat, self.network, "not_required" if self.fee_msat == 0 else "unpaid"))
            record_id = db.execute("SELECT id FROM records WHERE sha256 = ?", (digest,)).fetchone()["id"]
        return self.receipt(record_id)

    def get(self, record_id: str) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise RegistryError("Registro nao encontrado.")
        result = dict(row)
        if result["issuer_key_sha256"] != fingerprint(self.key().public_key()):
            raise RegistryError("A chave do emissor nao corresponde ao registro.")
        return result

    def update(self, record_id: str, **changes) -> None:
        allowed = {"invoice", "payment_hash", "expires_at", "payment_status", "paid_at", "proof", "bitcoin_verification"}
        if not changes or not set(changes) <= allowed:
            raise RegistryError("Atualizacao interna invalida.")
        self.get(record_id)
        with self.connection() as db:
            db.execute("UPDATE records SET " + ", ".join(f"{field} = ?" for field in changes) + " WHERE id = ?",
                       (*changes.values(), record_id))

    def require_paid(self, record_id: str) -> dict:
        row = self.get(record_id)
        if row["payment_status"] not in {"paid", "not_required"}:
            raise RegistryError("Aguardando confirmacao do pagamento da tarifa do servico.")
        return row

    def receipt(self, record_id: str) -> dict:
        row = self.get(record_id)
        verified = json.loads(row["bitcoin_verification"]) if row["bitcoin_verification"] else None
        payload = {
            "schema": "cartorio-documentos/v1", "record_id": row["id"],
            "issuer_key_sha256": row["issuer_key_sha256"],
            "document": {"hash_algorithm": "SHA-256", "sha256": row["sha256"], "size_bytes": row["size_bytes"]},
            "registered_at_server": row["registered_at"], "issued_at_server": now(),
            "payment": {"fee_msat": row["fee_msat"], "network": row["network"],
                        "status": row["payment_status"], "paid_at": row["paid_at"]},
            "bitcoin": {"status": "verified_at_check" if verified else ("pending" if row["proof"] else "not_submitted"),
                        "proof_sha256": hashlib.sha256(row["proof"]).hexdigest() if row["proof"] else None,
                        "last_verification": verified},
            "scope": "Integridade e prova de existencia. Nao atesta autoria, identidade, conteudo verdadeiro ou autorizacao de transferencias.",
        }
        signature = self.key().sign(canonical(payload))
        return {"payload": payload, "signature_ed25519": base64.b64encode(signature).decode("ascii")}
