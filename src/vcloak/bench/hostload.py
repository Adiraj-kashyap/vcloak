"""M15 S2: what the host did during a cell: CPU utilisation (psutil) and the size of the cell's data in PostgreSQL.

Both are context of the latency numbers, not results on their own: the generator, the service and the database
share one machine, so a busy CPU is part of every latency of the cell. Without psutil, or without PostgreSQL,
the answer is `available: false` with the reason, never a guess.
"""
from __future__ import annotations

import csv
import importlib
import re
import threading
import time
from pathlib import Path
from typing import Any

CPU_FIELDS = ("ts", "cpu_pct", "cpu_max_core_pct", "service_cpu_pct", "generator_cpu_pct", "service_rss_mb")
CELL_SCHEMA_RE = re.compile(r"e2e_[a-z0-9_]{1,48}")  # the only schemas this module drops


def _psutil() -> Any | None:
    try:
        return importlib.import_module("psutil")
    except ImportError:
        return None


def power_state() -> dict[str, Any]:
    """What the machine reports about its power source (audit A1). A cloud runner reports no battery."""
    ps = _psutil()
    if ps is None:
        return {"available": False, "reason": "psutil is not installed"}
    try:
        b = ps.sensors_battery()
    except (AttributeError, OSError):
        b = None
    if b is None:
        return {"available": True, "battery": False, "power_plugged": None}
    return {"available": True, "battery": True, "power_plugged": bool(b.power_plugged), "percent": float(b.percent)}


class CpuSampler:
    """Background sampler writing `cpu.csv`: the whole machine, its busiest core, and the two processes of the
    cell (the service with its children, and this generator). Percentages of one core for the processes (a
    process on two cores reads 200), of all cores for the machine: psutil's conventions, stated in the summary."""

    def __init__(self, path: str | Path, service_pid: int | None, hz: float = 2.0) -> None:
        self.path, self.period, self.service_pid = Path(path), 1.0 / hz, service_pid
        self.hz, self.available, self.samples, self.reason = hz, False, 0, ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _procs(self, ps: Any, pid: int | None) -> list[Any]:
        if pid is None:
            return []
        try:
            root = ps.Process(pid)
            return [root, *root.children(recursive=True)]
        except ps.Error:
            return []

    def _loop(self, ps: Any) -> None:
        me = ps.Process()
        service = self._procs(ps, self.service_pid)
        for p in (me, *service):  # the first call of cpu_percent only sets the reference point
            with _ignore(ps):
                p.cpu_percent(None)
        ps.cpu_percent(None, percpu=True)
        with self.path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(CPU_FIELDS)
            while not self._stop.wait(self.period):
                cores = ps.cpu_percent(None, percpu=True)
                svc, rss = None, None
                if service:
                    svc, rss = 0.0, 0.0
                    for p in service:
                        with _ignore(ps):
                            svc += p.cpu_percent(None)
                            rss += p.memory_info().rss / 2**20
                w.writerow([f"{time.time():.3f}", f"{sum(cores) / len(cores):.1f}", f"{max(cores):.1f}",
                            "" if svc is None else f"{svc:.1f}", f"{me.cpu_percent(None):.1f}",
                            "" if rss is None else f"{rss:.1f}"])
                self.samples += 1

    def start(self) -> CpuSampler:
        ps = _psutil()
        if ps is None:
            self.reason = "psutil is not installed"
            return self
        self.available = True
        self._thread = threading.Thread(target=self._loop, args=(ps,), daemon=True)
        self._thread.start()
        return self

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        out: dict[str, Any] = {"available": self.available, "samples": self.samples, "hz": self.hz,
                               "file": self.path.name if self.available else None,
                               "service_process": self.service_pid is not None}
        if not self.available:
            out["reason"] = self.reason
        return out


class _ignore:
    """A process of the cell may end while it is sampled: that sample is skipped, the sampler goes on."""

    def __init__(self, ps: Any) -> None:
        self._err = ps.Error

    def __enter__(self) -> None:
        return None

    def __exit__(self, kind: Any, *rest: object) -> bool:
        return kind is not None and issubclass(kind, self._err)


# ---------------------------------------------------------------- PostgreSQL: the data of one cell

def _connect(dsn: str | None) -> Any:
    import psycopg

    from vcloak.storage import pgconf

    return psycopg.connect(dsn or pgconf.default_dsn(), autocommit=True)


def check_cell_schema(schema: str) -> str:
    if not CELL_SCHEMA_RE.fullmatch(schema):
        raise ValueError(f"a cell schema must match {CELL_SCHEMA_RE.pattern}, got {schema!r}")
    return schema


def drop_cell_schema(dsn: str | None, schema: str) -> None:
    """Remove what an earlier run left under this cell's name, so every cell starts on an empty store. Only a
    schema named `e2e_...` can be dropped here: never `public`, never the baseline schema of the demo."""
    check_cell_schema(schema)
    with _connect(dsn) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


def db_size(dsn: str | None, schema: str | None) -> dict[str, Any]:
    """Bytes the tables of `schema` occupy (heap, indexes and TOAST: `pg_total_relation_size`), how many tables
    that is, and the size of the whole database, which also holds whatever other runs left in it."""
    try:
        with _connect(dsn) as conn:
            total = conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
            if schema is None:
                return {"available": True, "schema": None, "database_bytes": int(total),
                        "note": "no schema of its own: the cell shares the default schema with earlier runs"}
            got = conn.execute(
                "SELECT count(*), coalesce(sum(pg_total_relation_size(c.oid)), 0) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = %s AND c.relkind IN ('r', 'm')",
                (schema,)).fetchone()
        return {"available": True, "schema": schema, "tables": int(got[0]), "schema_bytes": int(got[1]),
                "database_bytes": int(total)}
    except Exception as e:  # noqa: BLE001 - the size is context: a failure is recorded, the cell stands
        return {"available": False, "reason": f"{type(e).__name__}: {str(e)[:160]}"}
