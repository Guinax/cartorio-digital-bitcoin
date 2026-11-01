#!/usr/bin/env python3
"""Cinco pagamentos ficticios A -> B -> C; mede taxas novas do no B.

Executar da raiz do repositorio:
    python3 laboratorio-lightning/teste_taxas.py

Nao usa BTC real; precisa do laboratorio regtest ja iniciado.
"""
from __future__ import annotations

import sys
import time
import uuid

from run_lab import ln, normal_channel


PAYMENTS = 5
AMOUNT_MSAT = 5_000_000


def amount_msat(value: object) -> int:
    return int(str(value).removesuffix("msat"))


def snapshot() -> tuple[int, int]:
    settled = ln("b", "listforwards", "settled").get("forwards", [])
    return (
        len(settled),
        sum(amount_msat(item.get("fee_msat", 0)) for item in settled),
    )


def main() -> None:
    print("CARTORIO DIGITAL BITCOIN | TESTE DE 5 PAGAMENTOS REGTEST", flush=True)
    ids = {node: ln(node, "getinfo")["id"] for node in ("a", "b", "c")}

    if not normal_channel("a", ids["b"]) or not normal_channel("b", ids["c"]):
        raise RuntimeError(
            "Canais Lightning nao estao ativos. Execute primeiro: "
            "python3 laboratorio-lightning/run_lab.py"
        )

    before_count, before_fees = snapshot()
    print(
        f"Antes: {before_count} encaminhamentos liquidados; "
        f"{before_fees} msat em taxas acumuladas.",
        flush=True,
    )

    for i in range(1, PAYMENTS + 1):
        label = f"cartorio-lote-{uuid.uuid4().hex[:16]}"
        invoice = ln(
            "c", "invoice", f"{AMOUNT_MSAT}msat", label,
            f"Teste ficticio de roteamento {i} de {PAYMENTS}"
        )["bolt11"]
        payment = ln("a", "pay", invoice)
        if payment.get("status") not in ("complete", "paid"):
            raise RuntimeError(
                f"Pagamento {i} nao confirmou sucesso: {payment.get('status')!r}"
            )
        print(f"Pagamento {i}/{PAYMENTS}: confirmado.", flush=True)

    # O registro de encaminhamentos pode levar um instante para atualizar.
    deadline = time.monotonic() + 30
    while True:
        after_count, after_fees = snapshot()
        new_count = after_count - before_count
        new_fees = after_fees - before_fees
        if new_count >= PAYMENTS and new_fees > 0:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Pagamentos foram enviados, mas o relatorio nao confirmou "
                f"{PAYMENTS} encaminhamentos com taxa. "
                f"Novos encaminhamentos: {new_count}; taxa: {new_fees} msat."
            )
        time.sleep(2)

    print()
    print(f"Novos encaminhamentos liquidados: {new_count}")
    print(f"Novas taxas no no B: {new_fees} msat ({new_fees / 1000:.3f} sat)")
    print(f"Total de taxas registradas: {after_fees} msat")
    print("SUCESSO: cinco pagamentos ficticios e taxas verificadas no no B.")
    print("ATENCAO: nao sao ganhos reais. Encerre o Codespace ao terminar.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        sys.exit(1)
