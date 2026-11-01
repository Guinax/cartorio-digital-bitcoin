"""Arquivos privados e transporte autenticado sem redirecionamento."""
import json
import os
import ssl
import stat
import tempfile
from pathlib import Path
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, build_opener

from .registry import RegistryError


def private_read(path: str | Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise RegistryError("Arquivo secreto precisa ser regular e acessivel somente ao proprietario (0600/0400).")
        value = source.read(16385)
    if len(value) > 16384 or not value.strip():
        raise RegistryError("Arquivo secreto vazio ou excessivamente grande.")
    return value.strip()


def atomic_private(path: str | Path, data: bytes) -> None:
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=".cartorio-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RegistryError("Redirecionamento de uma conexao autenticada recusado.")


def secure_opener(ca_file=None):
    # Credenciais locais nao passam por proxies do ambiente.
    context = ssl.create_default_context(cafile=ca_file)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return build_opener(ProxyHandler({}), HTTPSHandler(context=context), NoRedirect())


def read_json(response, limit=1024 * 1024):
    raw = response.read(limit + 1)
    if len(raw) > limit:
        raise RegistryError("Resposta remota excedeu o limite permitido.")
    return json.loads(raw)
