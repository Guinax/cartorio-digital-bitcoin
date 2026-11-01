#!/usr/bin/env python3
"""Documento -> fatura -> A -> B -> C, somente regtest, sem BTC real.

Uso na raiz, com as dependencias instaladas:
    python3 laboratorio-lightning/teste_documentos.py --preparar

Nao envia dados a calendarios publicos nem apaga volumes existentes.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import run_lab

ROOT = Path(__file__).resolve().parent.parent
FEE_MSAT = 2_500_000


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def assert_regtest(bitcoin_info: dict, nodes: dict[str, dict]) -> None:
    """Obrigatorio antes de qualquer pagamento automatico do teste."""
    require(bitcoin_info.get("chain") == "regtest", "Interrompido: Bitcoin nao esta em regtest.")
    require(set(nodes) == {"a", "b", "c"}, "Interrompido: os tres nos precisam ser conferidos.")
    for name, info in nodes.items():
        require(info.get("network") == "regtest", f"Interrompido: no {name.upper()} fora de regtest.")


def lab_state() -> dict[str, dict]:
    bitcoin = run_lab.json_result(run_lab.btc("getblockchaininfo"), "bitcoin getblockchaininfo")
    nodes = {name: run_lab.ln(name, "getinfo") for name in ("a", "b", "c")}
    assert_regtest(bitcoin, nodes)
    return nodes


def cli(data: Path, *args: str, expect_failure: bool = False) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "cartorio_documentos", "--data", str(data),
         "--network", "regtest", "--fee-msat", str(FEE_MSAT), *args],
        cwd=ROOT, env=os.environ.copy(), capture_output=True, text=True, timeout=60, check=False,
    )
    if expect_failure:
        require(result.returncode == 1, "O comando deveria recusar a operacao.")
        error = json.loads(result.stderr)
        require(isinstance(error.get("error"), str), "A recusa precisa ser um erro estruturado.")
        return error
    require(result.returncode == 0, f"Comando {args[0]} falhou: {result.stderr[-2000:]}")
    return json.loads(result.stdout)


def run_test() -> dict:
    nodes = lab_state()
    require(run_lab.normal_channel("a", nodes["b"]["id"]), "Canal A -> B nao esta ativo.")
    require(run_lab.normal_channel("b", nodes["c"]["id"]), "Canal B -> C nao esta ativo.")
    with tempfile.TemporaryDirectory(prefix="cartorio-documentos-regtest-") as tmp:
        directory = Path(tmp)
        data, document = directory / "state", directory / "documento-teste.txt"
        document.write_text("Documento sintetico para teste de integracao. Sem dados pessoais.\n", encoding="utf-8")
        print("• Registrando documento e conferindo assinatura...", flush=True)
        cli(data, "init")
        receipt = cli(data, "register", str(document))
        record_id = receipt["payload"]["record_id"]
        require(receipt["payload"]["payment"]["status"] == "unpaid", "Registro deveria exigir pagamento.")
        repeated = cli(data, "register", str(document))
        require(repeated["payload"]["record_id"] == record_id, "Registro duplicou o documento.")
        receipt_path = directory / "comprovante.json"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        verified = cli(data, "verify-receipt", str(document), "--receipt", str(receipt_path),
                       "--public-key", str(data / "issuer-public.pem"))
        require(verified["signature_valid"] and verified["document_matches"], "Comprovante nao confere.")
        blocked = cli(data, "stamp", record_id, expect_failure=True)
        require("pagamento" in blocked["error"].lower(), "Registro nao foi bloqueado por falta de pagamento.")
        before = cli(data, "forwards", "--lab")

        print("• Gerando fatura e conferindo que ainda esta pendente...", flush=True)
        invoice = cli(data, "invoice", record_id, "--lab")
        require(invoice["network"] == "regtest" and invoice["bolt11"].lower().startswith("lnbcrt"),
                "Interrompido: fatura nao pertence a regtest.")
        require(invoice["fee_msat"] == FEE_MSAT, "Valor da fatura diferente da tarifa de teste.")
        recovered = cli(data, "invoice", record_id, "--lab")
        require(recovered["bolt11"] == invoice["bolt11"], "A tentativa repetida gerou outra fatura.")
        pending = cli(data, "sync-payment", record_id, "--lab")
        require(pending["payload"]["payment"]["status"] == "unpaid", "Fatura nao paga foi marcada como paga.")

        print("• Pagando fatura ficticia de A para C, passando por B...", flush=True)
        lab_state()
        run_lab.ln("a", "pay", invoice["bolt11"])
        paid = cli(data, "sync-payment", record_id, "--lab")
        require(paid["payload"]["payment"]["status"] == "paid", "Recebimento nao confirmado no no C.")
        require(paid["payload"]["payment"]["paid_at"] is not None, "Recebimento sem horario de liquidacao.")
        from cartorio_documentos.registry import Registry
        Registry(data).require_paid(record_id)
        receipt_path.write_text(json.dumps(paid), encoding="utf-8")
        cli(data, "verify-receipt", str(document), "--receipt", str(receipt_path),
            "--public-key", str(data / "issuer-public.pem"))
        deadline = time.monotonic() + 30
        while True:
            after = cli(data, "forwards", "--lab")
            new_count = after["settled_forwards_retained"] - before["settled_forwards_retained"]
            new_fees = after["fees_msat_retained"] - before["fees_msat_retained"]
            if new_count >= 1 and new_fees > 0:
                break
            require(time.monotonic() < deadline, "A taxa de B ainda nao foi confirmada apos o pagamento.")
            time.sleep(2)

        print("• Conferindo recusa do documento alterado...", flush=True)
        document.write_text("Arquivo alterado apos o registro.\n", encoding="utf-8")
        rejected = cli(data, "verify-receipt", str(document), "--receipt", str(receipt_path),
                       "--public-key", str(data / "issuer-public.pem"), expect_failure=True)
        require("documento" in rejected["error"].lower(), "Documento alterado nao foi recusado corretamente.")
        return {
            "result": "passed", "tested_at_utc": datetime.now(timezone.utc).isoformat(),
            "network": "regtest", "real_btc_moved": False,
            "signed_receipt_verified": True, "altered_document_rejected": True,
            "unpaid_stamp_blocked": True, "duplicate_invoice_avoided": True,
            "payment_status": "paid", "service_fee_msat_fictitious": FEE_MSAT,
            "new_settled_forwards": new_count, "new_routing_fees_msat_fictitious": new_fees,
            "bitcoin_mainnet_timestamp_verified": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preparar", action="store_true", help="Inicia ou retoma o lab sem apagar volumes.")
    parser.add_argument("--output", type=Path, help="Grava somente o resumo, sem chaves ou dados da fatura.")
    args = parser.parse_args()
    try:
        missing = [name for name in ("cryptography", "opentimestamps", "bitcoin")
                   if importlib.util.find_spec(name) is None]
        require(not missing, "Instale as dependencias: python3 -m pip install -r requirements-documentos.txt")
        sys.path.insert(0, str(ROOT))
        print("CARTORIO DIGITAL BITCOIN | DOCUMENTOS + LIGHTNING REGTEST", flush=True)
        if args.preparar:
            run_lab.main()
        summary = run_test()
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        print("SUCESSO: comprovante, recebimento ficticio e novas taxas verificados.", flush=True)
        return 0
    except (RuntimeError, ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        print("Diagnostico: docker compose -f laboratorio-lightning/compose.yaml logs --tail=80", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
