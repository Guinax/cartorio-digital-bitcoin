"""Snapshot SQLite e chave do emissor, em backup autenticado e criptografado."""
import base64
import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .registry import Registry, RegistryError, fingerprint, now
from .security import atomic_private, private_read

MAX_DATABASE = 64 * 1024 * 1024
MAX_ARCHIVE = 128 * 1024 * 1024


def decode_archive(path, backup_key_file) -> dict:
    if Path(path).stat().st_size > MAX_ARCHIVE:
        raise RegistryError("Backup excede o limite desta versao (128 MiB).")
    try:
        raw = Fernet(private_read(backup_key_file)).decrypt(Path(path).read_bytes())
        data = json.loads(raw)
        if data["schema"] != "cartorio-backup/v1":
            raise RegistryError("Formato de backup desconhecido.")
        return data
    except (InvalidToken, ValueError, KeyError, TypeError) as exc:
        raise RegistryError("Backup ou chave de backup invalidos.") from exc


def create_backup(registry: Registry, backup_dir: Path, backup_key_file: Path) -> dict:
    key = registry.key()
    backup_dir = Path(backup_dir).resolve()
    if backup_dir.is_relative_to(registry.directory):
        raise RegistryError("O backup deve ficar fora do diretorio de dados.")
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if backup_dir.stat().st_mode & 0o077:
        raise RegistryError("Diretorio de backup exige permissoes 0700.")
    fernet = Fernet(private_read(backup_key_file))
    with tempfile.TemporaryDirectory(prefix=".snapshot-", dir=registry.directory) as temp:
        snapshot = Path(temp) / "registry.sqlite3"
        fd = os.open(snapshot, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        with registry.connection() as source, closing(sqlite3.connect(snapshot)) as target:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RegistryError("Snapshot SQLite nao passou na verificacao de integridade.")
            count = target.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        if snapshot.stat().st_size > MAX_DATABASE:
            raise RegistryError("Banco excede 64 MiB; configure uma solucao de backup de maior escala antes de continuar.")
        database = snapshot.read_bytes()
    identity = fingerprint(key.public_key())
    created_at = now()
    payload = {"schema": "cartorio-backup/v1", "created_at": created_at,
               "issuer_key_sha256": identity, "records": count,
               "database_sha256": hashlib.sha256(database).hexdigest(),
               "database": base64.b64encode(database).decode(),
               "private_key": base64.b64encode(registry.key_path.read_bytes()).decode()}
    archive = fernet.encrypt(json.dumps(payload, separators=(",", ":")).encode())
    if len(archive) > MAX_ARCHIVE:
        raise RegistryError("Arquivo de backup excede 128 MiB.")
    # mkstemp impede colisao e mantem permissoes privadas desde a criacao.
    fd, target = tempfile.mkstemp(prefix="cartorio-", suffix=".backup", dir=backup_dir)
    with os.fdopen(fd, "wb") as output:
        output.write(archive)
        output.flush()
        os.fsync(output.fileno())
    status = {"created_at": created_at, "path": target, "sha256": hashlib.sha256(archive).hexdigest(),
              "issuer_key_sha256": identity, "records": count}
    atomic_private(registry.directory / "backup-status.json", json.dumps(status).encode())
    return status


def restore_backup(archive, destination: Path, backup_key_file, password: bytes, expected_issuer: str) -> dict:
    destination = Path(destination).resolve()
    if destination.exists():
        raise RegistryError("Restauracao exige um diretorio novo; dados existentes nunca sao sobrescritos.")
    payload = decode_archive(archive, backup_key_file)
    try:
        database = base64.b64decode(payload["database"], validate=True)
        private_key = base64.b64decode(payload["private_key"], validate=True)
        encrypted = b"ENCRYPTED PRIVATE KEY" in private_key
        key = serialization.load_pem_private_key(private_key, password=password if encrypted else None)
        if not isinstance(key, Ed25519PrivateKey):
            raise RegistryError("Chave do backup nao e Ed25519.")
        identity = fingerprint(key.public_key())
        if identity != expected_issuer or identity != payload["issuer_key_sha256"]:
            raise RegistryError("Emissor do backup nao corresponde ao emissor confiavel informado.")
        if len(database) > MAX_DATABASE or hashlib.sha256(database).hexdigest() != payload["database_sha256"]:
            raise RegistryError("Snapshot do backup nao confere.")
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, RegistryError):
            raise
        raise RegistryError("Conteudo do backup ou senha da chave invalidos.") from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=destination.parent) as temp:
        stage = Path(temp)
        atomic_private(stage / "registry.sqlite3", database)
        atomic_private(stage / "issuer-private.pem", private_key)
        restored = Registry(stage, password=password)
        with restored.connection() as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RegistryError("Banco restaurado invalido.")
            rows = db.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            if rows != payload["records"] or db.execute(
                    "SELECT 1 FROM records WHERE issuer_key_sha256 != ? LIMIT 1", (identity,)).fetchone():
                raise RegistryError("Registros restaurados nao correspondem ao backup.")
        # mkdir exclusivo protege inclusive contra restauracao concorrente.
        destination.mkdir(mode=0o700)
        atomic_private(destination / "registry.sqlite3", database)
        atomic_private(destination / "issuer-private.pem", private_key)
    Registry(destination, password=password).initialize()
    return {"restored": True, "records": rows, "issuer_key_sha256": identity, "directory": str(destination)}
