"""Cobranca do servico e consulta de encaminhamentos do proprio no CLN."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request

from .registry import Registry, RegistryError


def msat(value) -> int:
    if type(value) is int:
        return value
    if isinstance(value, str):
        return int(value.removesuffix("msat"))
    raise RegistryError("Valor Lightning em msat invalido.")


class CoreLightning:
    def __init__(self, command: list[str], network: str):
        if not command or not all(isinstance(p, str) and p for p in command):
            raise RegistryError("Configure o comando lightning-cli como lista JSON de argumentos.")
        self.command, self.network = command, network

    def call(self, method: str, **params):
        if method not in {"getinfo", "invoice", "listinvoices", "listforwards", "listpeerchannels"}:
            raise RegistryError("Operacao Lightning nao permitida pelo modulo de documentos.")
        try:
            result = subprocess.run([*self.command, "--json", "--notifications=none", "-k", method,
                                     *[f"{k}={v}" for k, v in params.items()]],
                                    capture_output=True, text=True, timeout=30, check=False)
            if result.returncode:
                raise RegistryError("Core Lightning recusou a consulta. Confira o no e seu socket RPC.")
            data = json.loads(result.stdout)
            if "error" in data:
                raise RegistryError("Core Lightning retornou erro.")
            return data
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            raise RegistryError("Core Lightning indisponivel ou resposta invalida.") from exc

    def ensure_network(self, expected: str) -> None:
        if self.network != expected or self.call("getinfo").get("network") != expected:
            raise RegistryError("Rede do no diferente da rede deste registro. Pagamento nao confirmado.")


class CoreLightningREST:
    """CLNRest HTTPS com Rune restrita; sem socket RPC da carteira no processo."""
    def __init__(self, url: str, rune_file: str | Path, ca_file: str | Path, *, invoice_gate=None, node_id=None):
        from .security import secure_opener
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
            raise RegistryError("CLNRest exige URL HTTPS de origem, sem credenciais, caminho ou parametros.")
        self.url, self.rune_file, self.network = url.rstrip("/"), Path(rune_file), "bitcoin"
        self.opener = secure_opener(str(ca_file) if ca_file else None)
        self.invoice_gate = invoice_gate
        self.expected_node_id = node_id

    def call(self, method: str, **params):
        from .security import private_read, read_json
        if method not in {"getinfo", "invoice", "listinvoices", "listforwards", "listpeerchannels"}:
            raise RegistryError("Operacao Lightning nao permitida neste cliente restrito.")
        if method == "invoice" and self.invoice_gate:
            self.invoice_gate(msat(params["amount_msat"]))
        rune = private_read(self.rune_file).decode("ascii")
        if "\r" in rune or "\n" in rune:
            raise RegistryError("Credencial Rune invalida.")
        request = Request(self.url + "/v1/" + method, data=json.dumps(params).encode(),
                          headers={"Content-Type": "application/json", "Rune": rune})
        try:
            with self.opener.open(request, timeout=20) as response:
                result = read_json(response)
        except Exception as exc:
            raise RegistryError("CLNRest indisponivel ou credencial/certificado recusado.") from exc
        if not isinstance(result, dict) or "error" in result:
            raise RegistryError("Resposta CLNRest invalida.")
        return result

    def ensure_network(self, expected: str) -> None:
        info = self.call("getinfo")
        if expected != "bitcoin" or info.get("network") != "bitcoin":
            raise RegistryError("O perfil de producao exige Lightning na rede bitcoin.")
        if self.expected_node_id and info.get("id") != self.expected_node_id:
            raise RegistryError("Identidade do no Lightning diferente da configurada.")
        if info.get("warning_bitcoind_sync") or info.get("warning_lightningd_sync"):
            raise RegistryError("O no Lightning ainda nao esta sincronizado.")


def invoice_for(registry: Registry, record_id: str, node: CoreLightning) -> dict:
    row = registry.get(record_id)
    if row["fee_msat"] == 0:
        raise RegistryError("Este registro nao exige pagamento. Defina uma tarifa antes de registrar outro documento.")
    node.ensure_network(row["network"])
    label = "cartorio-documento-" + record_id
    invoices = node.call("listinvoices", label=label).get("invoices", [])
    if not invoices:
        node.call("invoice", amount_msat=f"{row['fee_msat']}msat", label=label,
                  description="Registro de integridade de documento " + record_id, expiry=3600)
        invoices = node.call("listinvoices", label=label).get("invoices", [])
    if len(invoices) != 1:
        raise RegistryError("Fatura nao encontrada ou ambigua. Tente novamente para recuperar pelo identificador.")
    item = invoices[0]
    _validate_invoice(row, item, label)
    registry.update(record_id, invoice=item["bolt11"], payment_hash=item["payment_hash"], expires_at=item["expires_at"])
    return {"record_id": record_id, "bolt11": item["bolt11"], "fee_msat": row["fee_msat"],
            "network": row["network"], "expires_at": item["expires_at"], "status": item["status"]}


def _validate_invoice(row: dict, item: dict, label: str) -> None:
    invoice = item.get("bolt11", "").lower()
    invoice_network = "regtest" if invoice.startswith("lnbcrt") else ("testnet" if invoice.startswith("lntb") else
                       ("bitcoin" if invoice.startswith("lnbc") else "unknown"))
    network_matches = invoice_network == row["network"] or (row["network"] == "signet" and invoice_network == "testnet")
    if item.get("label") != label or msat(item.get("amount_msat")) != row["fee_msat"] or not network_matches:
        raise RegistryError("Fatura nao corresponde ao identificador, valor ou rede do registro.")
    if row["payment_hash"] and item.get("payment_hash") != row["payment_hash"]:
        raise RegistryError("Hash de pagamento diferente do registrado.")


def sync_payment(registry: Registry, record_id: str, node: CoreLightning) -> dict:
    row = registry.get(record_id)
    if row["payment_status"] == "not_required":
        return registry.receipt(record_id)
    node.ensure_network(row["network"])
    if not row["payment_hash"]:
        raise RegistryError("Crie ou recupere a fatura primeiro.")
    label = "cartorio-documento-" + record_id
    invoices = node.call("listinvoices", label=label).get("invoices", [])
    if len(invoices) != 1:
        raise RegistryError("Nao foi possivel confirmar a fatura no proprio no.")
    item = invoices[0]
    _validate_invoice(row, item, label)
    status = item["status"]
    if status == "paid":
        try:
            preimage = bytes.fromhex(item["payment_preimage"])
        except (KeyError, ValueError) as exc:
            raise RegistryError("Comprovacao de pagamento ausente ou invalida.") from exc
        if len(preimage) != 32 or hashlib.sha256(preimage).hexdigest() != row["payment_hash"]:
            raise RegistryError("Comprovacao criptografica de pagamento invalida.")
        if msat(item.get("amount_received_msat")) < row["fee_msat"]:
            raise RegistryError("Valor recebido menor que a tarifa registrada.")
        registry.update(record_id, payment_status="paid", paid_at=item["paid_at"])
    elif status in {"unpaid", "expired"}:
        if row["payment_status"] == "paid":
            raise RegistryError("Estado do no contradiz pagamento confirmado. Confira backups e banco.")
        registry.update(record_id, payment_status=status)
    else:
        raise RegistryError("Estado de pagamento desconhecido.")
    return registry.receipt(record_id)


def forwarding_report(node: CoreLightning) -> dict:
    node.ensure_network(node.network)
    forwards = node.call("listforwards", status="settled").get("forwards", [])
    settled = [row for row in forwards if row.get("status") == "settled"]
    return {"network": node.network, "settled_forwards_retained": len(settled),
            "fees_msat_retained": sum(msat(row.get("fee_msat", 0)) for row in settled),
            "scope": "Somente encaminhamentos liquidados conservados pelo proprio no. Nao sao todas as transacoes Bitcoin."}
