#!/usr/bin/env python3
"""Regtest local: A -> B -> C com taxa automatica em B.

Uso: python3 laboratorio-lightning/run_lab.py (a partir da raiz do repositorio).
Nenhum bitcoin real e movimentado. O Codespaces pode consumir franquia/custos.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

COMPOSE = str(Path(__file__).resolve().with_name("compose.yaml"))
RPCUSER = "lab"
RPCPASS = "apenas-regtest-sem-valor"


def command(args: list[str], *, check: bool = True) -> str:
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    if result.returncode and check:
        raise RuntimeError(
            f"Falhou: {' '.join(args[:7])}\n"
            f"{result.stderr[-2500:]}\n{result.stdout[-800:]}"
        )
    return result.stdout.strip()


def compose(*args: str) -> str:
    return command(["docker", "compose", "-f", COMPOSE, *args])


def btc(*args: str) -> str:
    return compose(
        "exec", "-T", "bitcoin", "bitcoin-cli", "-regtest",
        f"-rpcuser={RPCUSER}", f"-rpcpassword={RPCPASS}", *args
    )


def wallet(*args: str) -> str:
    return btc("-rpcwallet=lab-miner", *args)


def json_result(output: str, origin: str):
    """Mostra a operacao e uma amostra da resposta se nao for JSON valido."""
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        preview = output[:500] if output else "(resposta vazia)"
        raise RuntimeError(
            f"{origin} nao retornou JSON valido. Inicio da resposta: {preview!r}"
        ) from exc


def ln(node: str, *args: str) -> dict:
    # Nao permitir notificacoes '# ...' antes do JSON (ex.: comando pay).
    output = compose("exec", "-T", f"lightning-{node}",
                     "lightning-cli", "--network=regtest",
                     "--json", "--notifications=none", *args)
    operation = args[0] if args else "(sem comando)"
    return json_result(output, f"lightning-{node} {operation}")


def retry(message: str, fn, timeout: int = 120, interval: int = 3):
    print(f"• {message}", flush=True)
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            result = fn()
            if result is not False:
                return result
        except (RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(interval)
    raise RuntimeError(f"Tempo excedido: {message}. Ultimo erro: {last_error}")


def mine(blocks: int) -> None:
    address = wallet("getnewaddress")
    btc("generatetoaddress", str(blocks), address)


def ensure_wallet() -> None:
    wallets = json_result(btc("listwalletdir"), "bitcoin listwalletdir")["wallets"]
    names = {w["name"] for w in wallets}
    if "lab-miner" not in names:
        btc("createwallet", "lab-miner")
    else:
        loaded = json_result(btc("listwallets"), "bitcoin listwallets")
        if "lab-miner" not in loaded:
            btc("loadwallet", "lab-miner")


def funds(node: str) -> int:
    outputs = ln(node, "listfunds").get("outputs", [])
    return sum(
        int(str(item.get("amount_msat", 0)).replace("msat", ""))
        for item in outputs if item.get("status") == "confirmed"
    )


def normal_channel(node: str, peer_id: str) -> bool:
    channels = ln(node, "listpeerchannels").get("channels", [])
    return any(
        c.get("peer_id") == peer_id and c.get("state") == "CHANNELD_NORMAL"
        for c in channels
    )


def existing_channel(node: str, peer_id: str) -> bool:
    channels = ln(node, "listpeerchannels").get("channels", [])
    return any(
        c.get("peer_id") == peer_id and c.get("state") not in ("CLOSED", "ONCHAIN")
        for c in channels
    )


def report_fees() -> int:
    forwards = ln("b", "listforwards", "settled").get("forwards", [])
    total = sum(
        int(str(item.get("fee_msat", 0)).replace("msat", ""))
        for item in forwards
    )
    print(f"• Encaminhamentos liquidados em B: {len(forwards)}")
    print(f"• Taxas acumuladas em B: {total} msat ({total / 1000:.3f} satoshis)")
    return total


def main():
    print("CARTORIO DIGITAL BITCOIN | REGTEST, SEM BTC REAL", flush=True)
    print("• Iniciando quatro conteineres Docker...", flush=True)
    compose("up", "-d", "--build")
    retry("Aguardando Bitcoin Core", lambda: json_result(btc("getblockchaininfo"), "bitcoin getblockchaininfo"))
    for node in ("a", "b", "c"):
        retry(f"Aguardando Lightning {node.upper()}", lambda n=node: ln(n, "getinfo"), 180)

    ensure_wallet()
    height = int(btc("getblockcount"))
    if height < 105:
        print("• Gerando blocos de regtest para liberar fundos ficticios...", flush=True)
        mine(105 - height)

    ida, idb, idc = (ln(node, "getinfo")["id"] for node in ("a", "b", "c"))
    print("• Financiando A e B na rede ficticia...", flush=True)
    for node in ("a", "b"):
        if funds(node) < 1_200_000_000:
            address = ln(node, "newaddr")["bech32"]
            wallet("sendtoaddress", address, "0.025")
    mine(6)
    for node in ("a", "b"):
        retry(f"Confirmando saldo do no {node.upper()}",
              lambda n=node: funds(n) >= 1_100_000_000, 180)

    print("• Conectando A a B e B a C...", flush=True)
    ln("a", "connect", idb, "lightning-b", "9735")
    ln("b", "connect", idc, "lightning-c", "9735")
    if not existing_channel("a", idb):
        ln("a", "fundchannel", idb, "1000000")
    if not existing_channel("b", idc):
        ln("b", "fundchannel", idc, "1000000")
    mine(8)
    retry("Aguardando canal A -> B", lambda: normal_channel("a", idb), 240)
    retry("Aguardando canal B -> C", lambda: normal_channel("b", idc), 240)

    # Taxa base = 1000 msat; proporcional = 100 ppm.
    ln("b", "setchannel", idc, "1000", "100")
    print("• Taxas de roteamento configuradas no no B.", flush=True)

    label = f"cartorio-lab-{uuid.uuid4().hex[:12]}"
    invoice = ln("c", "invoice", "5000000msat", label,
                 "Pagamento ficticio para demonstrar roteamento")["bolt11"]
    print("• Enviando pagamento ficticio A -> B -> C...", flush=True)
    ln("a", "pay", invoice)
    total = report_fees()
    if total <= 0:
        raise RuntimeError("O pagamento nao gerou taxa positiva registrada no no B.")
    print("SUCESSO: pagamento ficticio roteado por B com taxa registrada!")
    print("Para desligar: docker compose -f laboratorio-lightning/compose.yaml down")
    print("ATENCAO: isso nao gera renda real; o Codespaces pode ter custos.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError) as exc:
        print(f"\nERRO: {exc}", file=sys.stderr)
        print(
            "Diagnostico: docker compose -f laboratorio-lightning/compose.yaml logs --tail=80",
            file=sys.stderr
        )
        sys.exit(1)
