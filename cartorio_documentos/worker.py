"""Fila persistente para reconciliar pagamentos e atualizar/revalidar provas."""
import fcntl
import json
import os
import signal
import threading
import time
from datetime import datetime

from .backup import create_backup
from .lightning import sync_payment
from .ots import stamp, upgrade, verify_bitcoin
from .production import bitcoin_for, doctor, node_for
from .registry import RegistryError, now
from .security import atomic_private


def run_once(config, registry, *, node=None, rpc=None, stop=None) -> dict:
    clock = time.time()
    try:
        status = json.loads((registry.directory / "backup-status.json").read_text())
        age = clock - datetime.fromisoformat(status["created_at"]).timestamp()
        due = not 0 <= age < config["backup_interval_seconds"]
    except (OSError, ValueError, KeyError):
        due = True
    if due:
        create_backup(registry, config["backup_dir"], config["backup_key_file"])
    node, rpc = node or node_for(config, registry), rpc or bitcoin_for(config)
    with registry.connection() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS processing_jobs (
            record_id TEXT PRIMARY KEY, next_run_at REAL NOT NULL,
            failures INTEGER NOT NULL DEFAULT 0, last_result TEXT NOT NULL)""")
        rows = db.execute("""SELECT r.id, COALESCE(j.failures, 0) AS failures
            FROM records r LEFT JOIN processing_jobs j ON j.record_id = r.id
            WHERE r.network = 'bitcoin' AND (j.next_run_at IS NULL OR j.next_run_at <= ?)
            ORDER BY COALESCE(j.next_run_at, 0), r.registered_at LIMIT ?""",
            (clock, config["max_records_per_cycle"])).fetchall()
    totals = {"processed": 0, "verified": 0, "waiting_payment": 0, "pending_verification": 0, "errors": 0}
    for row in rows:
        if stop is not None and stop.is_set():
            break
        record_id, failures = row["id"], row["failures"]
        outcome, delay = "error", config["worker_interval_seconds"]
        try:
            record = registry.get(record_id)
            if record["fee_msat"] > 0 and record["payment_hash"]:
                sync_payment(registry, record_id, node)
                record = registry.get(record_id)
            if record["payment_status"] not in {"paid", "not_required"}:
                outcome = "waiting_payment"
            else:
                stamp(registry, record_id)
                upgrade(registry, record_id)
                try:
                    verify_bitcoin(registry, record_id, rpc, min_confirmations=config["min_confirmations"])
                    outcome, delay = "verified", 3600
                except RegistryError:
                    # Ausencia de prova completa ou falha de rede nunca vira confirmacao.
                    outcome, delay = "pending_verification", 900
            failures = 0
        except Exception:
            failures += 1
            delay = min(21600, config["worker_interval_seconds"] * 2 ** min(failures, 6))
        totals["processed"] += 1
        totals["errors" if outcome == "error" else outcome] += 1
        with registry.connection() as db:
            db.execute("""INSERT INTO processing_jobs(record_id, next_run_at, failures, last_result)
                VALUES (?, ?, ?, ?) ON CONFLICT(record_id) DO UPDATE SET
                next_run_at=excluded.next_run_at, failures=excluded.failures, last_result=excluded.last_result""",
                (record_id, time.time() + delay, failures, outcome))
        atomic_private(registry.directory / "worker-status.json",
                       json.dumps({"checked_at": now(), "network": "bitcoin", "phase": "processing"}).encode())
    status = {"checked_at": now(), "network": "bitcoin", **totals}
    atomic_private(registry.directory / "worker-status.json", json.dumps(status).encode())
    status["health"] = doctor(config, registry, node=node, rpc=rpc)
    atomic_private(registry.directory / "worker-status.json", json.dumps(status).encode())
    return status


def work(config, registry, *, once=False):
    stop = threading.Event()
    lock_path = registry.directory / "worker.lock"
    fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    previous = {}
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RegistryError("Outro worker ja esta executando neste banco.") from exc
        if not once:
            for sig in (signal.SIGINT, signal.SIGTERM):
                previous[sig] = signal.signal(sig, lambda *_: stop.set())
        while not stop.is_set():
            result = run_once(config, registry, stop=stop)
            if once:
                return result
            print(json.dumps(result, ensure_ascii=False), flush=True)
            stop.wait(config["worker_interval_seconds"])
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        os.close(fd)
