"""Greenlight status-only adapter: mTLS credentials, no signer or wallet writes.

This does NOT create a Greenlight node, create invoices, move funds, fund
channels, or replace our existing guarded CLNRest invoice backend.
Requires the optional gl-client==0.3.4 SDK to be installed by the operator.
"""
from __future__ import annotations

import re
from pathlib import Path

from .registry import RegistryError
from .security import private_read

_NODE_ID = re.compile(r"0[23][0-9a-f]{64}")


def normalize_node_id(value) -> str:
    if isinstance(value, bytes):
        value = value.hex()
    if not isinstance(value, str):
        raise RegistryError("Greenlight retornou identidade de no desconhecida.")
    value = value.lower()
    if not _NODE_ID.fullmatch(value):
        raise RegistryError("Greenlight retornou uma identidade publica invalida.")
    return value


class GreenlightStatus:
    """Connect to an existing registered Greenlight node, read-only.

    The SDK is injected for tests and imported only when explicitly requested.
    Device credentials identify the operator and must NEVER be checked in.
    """

    def __init__(self, device_credentials_file: str | Path, expected_node_id: str,
                 network: str = "bitcoin", *, sdk=None):
        if network not in {"bitcoin", "testnet"}:
            raise RegistryError("Consulta Greenlight aceita somente bitcoin ou testnet.")
        self.network = network
        self.expected_node_id = normalize_node_id(expected_node_id)
        self.credentials_path = Path(device_credentials_file)
        self.sdk = sdk

    def check(self) -> dict:
        # Read secret credentials with O_NOFOLLOW and 0600/0400 before any RPC.
        data = private_read(self.credentials_path)
        sdk = self.sdk
        if sdk is None:
            try:
                import glclient as sdk
            except ImportError as exc:
                raise RegistryError("Biblioteca opcional ausente: instale gl-client==0.3.4.") from exc
        try:
            credentials = sdk.Credentials.from_bytes(data)
            # Schedule through official SDK on each connection: dynamic URI.
            scheduler = sdk.Scheduler(self.network, credentials)
            node = scheduler.node()
            info = node.get_info()
        except Exception as exc:
            # Never serialize provider exception: it may include credential data.
            raise RegistryError("Nao foi possivel autenticar ou consultar o no Greenlight.") from exc

        if not hasattr(info, "id") or not hasattr(info, "network"):
            raise RegistryError("Greenlight nao forneceu identidade e rede verificaveis.")
        identity = normalize_node_id(info.id)
        if identity != self.expected_node_id:
            raise RegistryError("Greenlight retornou um no diferente da identidade autorizada.")
        if info.network != self.network:
            raise RegistryError("Greenlight retornou uma rede diferente da rede esperada.")
        return {
            "provider": "greenlight",
            "network": self.network,
            "node_id": identity,
            "authenticated_identity": True,
            "read_only": True,
            "mainnet_invoices_enabled": False,
            "note": "Status de conexao apenas. Nao confirma signer online, liquidez, disponibilidade 24h ou carteira recuperavel.",
        }

    def call(self, method: str, **params):
        raise RegistryError("Esta integracao Greenlight e somente leitura; faturas e movimentacao indisponiveis.")
