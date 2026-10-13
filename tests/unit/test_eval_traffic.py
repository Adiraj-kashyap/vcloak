"""M14 S1: the traffic generator and its replay through the service (numpy simulator, SQLite: correctness only)."""
from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

import httpx
import numpy as np
import pytest

from vcloak import runs
from vcloak.crypto.client import decrypt_content
from vcloak.eval import traffic
from vcloak.gpu.runtime import get_backend
from vcloak.service.app import create_app
from vcloak.service.baseline import BaselineBackend, SqliteBaselineStore
from vcloak.service.scheduler import SimClock
from vcloak.storage.repo import SqliteRepo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))

import run_security_eval as rse  # noqa: E402

SMALL = dict(seed=7, n_conv=12, duration_s=40, buckets=4, window_s=5)  # 8 windows of 25 epochs


def seed_model(rng: np.random.Generator, n_conv: int, duration_s: float, rate: float) -> list[tuple[float, int]]:
    """The event loop of `simulate_traffic` in seed/vcloak_oracle.py, copied to compare against."""
    events = []
    for c in range(n_conv):
        t = rng.exponential(1 / rate)
        while t < duration_s:
            events.append((t, c))
            t += rng.exponential(2.0) if rng.random() < 0.7 else rng.exponential(1 / rate)
    events.sort()
    return events


class TestBurstEvents:
    def test_same_events_as_the_seed_oracle_for_the_same_generator_state(self) -> None:
        want = seed_model(np.random.default_rng(2026), 200, 900, 0.05)
        got = traffic.burst_events(np.random.default_rng(2026), 200, 900, 0.05)
        assert [(e.t_ms, e.conv) for e in got] == [(int(t * 1000), c) for t, c in want]

    def test_ranks_sequence_numbers_and_times(self) -> None:
        events = traffic.burst_events(np.random.default_rng(3), 30, 120, 0.05)
        assert [e.truth for e in events] == list(range(len(events)))
        assert [e.t_ms for e in events] == sorted(e.t_ms for e in events)
        assert all(0 <= e.t_ms < 120_000 for e in events)
        for c in range(30):
            assert [e.seq for e in events if e.conv == c] == list(range(sum(1 for e in events if e.conv == c)))

    def test_the_seed_decides_the_events(self) -> None:
        a = traffic.burst_events(np.random.default_rng(5), 20, 60, 0.05)
        assert a == traffic.burst_events(np.random.default_rng(5), 20, 60, 0.05)
        assert a != traffic.burst_events(np.random.default_rng(6), 20, 60, 0.05)

    @pytest.mark.parametrize("args", [(0, 10, 0.05), (5, 0, 0.05), (5, 10, 0)])
    def test_sizes_must_be_positive(self, args: tuple[int, float, float]) -> None:
        with pytest.raises(ValueError):
            traffic.burst_events(np.random.default_rng(1), *args)

    def test_conversation_keys_differ_by_seed_and_conversation(self) -> None:
        keys = {traffic.conversation_key(s, c) for s in (1, 2) for c in range(5)}
        assert len(keys) == 10 and all(len(k) == 32 for k in keys)


class TestS1:
    def test_every_message_is_stored_once_in_the_window_of_its_arrival(self) -> None:
        repo = SqliteRepo()
        res = rse.run_s1(repo, get_backend("numpy"), **SMALL)
        assert res["ok"], res["checks"]
        assert res["messages"] == res["rows_stored"] == res["accepted"] > 30
        assert res["epochs_passed"] == 40_000 // 200 + 1 == res["scheduler"]["epochs_written"]
        events = traffic.burst_events(np.random.default_rng(SMALL["seed"]), 12, 40, rse.RATE)
        want = Counter(e.t_ms // 5000 for e in events)
        assert res["rows_per_window"] == {str(w): n for w, n in sorted(want.items())}
        assert res["scheduler"]["windows_rewritten"] == len(want)
        assert res["scheduler"]["compute"]["is_gpu"] is False

    def test_a_lost_row_fails_the_checks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = SqliteRepo()
        dump = repo.dump
        monkeypatch.setattr(repo, "dump", lambda: dump()[1:])
        res = rse.run_s1(repo, get_backend("numpy"), **SMALL)
        assert not res["ok"]
        assert not res["checks"]["row_count_equals_message_count"]
        assert not res["checks"]["stored_ciphertexts_are_the_sent_ones"]

    def test_cli_writes_a_valid_run_with_the_seed_and_the_true_engine(self, tmp_path: Path) -> None:
        assert rse.main(["--stage", "s1", "--quick", "--store", "sqlite", "--backend", "numpy", "--seed", "11",
                         "--out", str(tmp_path)]) == 0
        (run_dir,) = tmp_path.iterdir()
        assert runs.validate_manifest(run_dir) == []
        m = runs.read_manifest(run_dir)
        assert m["seed"] == 11 and m["quick"] and m["status"] == "OK"
        assert m["params"]["db"] == "sqlite" and m["params"]["engine"] == "numpy-simulator"
        assert m["env"]["backend"] == "numpy"
        res = json.loads((run_dir / "s1_traffic.json").read_text(encoding="utf-8"))
        (metric,) = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))["metrics"]
        assert metric["id"] == "S-TRAFFIC-MSGS" and metric["value"] == res["messages"] == res["rows_stored"]


class TestReplay:
    def test_the_baseline_stores_every_event_and_the_ciphertexts_open_with_the_conversation_key(self) -> None:
        events = traffic.burst_events(np.random.default_rng(4), 6, 10, 0.2)
        store, clock = SqliteBaselineStore(), SimClock()
        backend = BaselineBackend(store, clock, window_s=5, epoch_ms=200)

        async def main() -> traffic.Replay:
            app = create_app(backend, web_dir=False)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                             base_url="http://vcloak.test") as client:
                    sent = await traffic.replay(backend, clock, client, events, seed=4, duration_ms=10_000,
                                                epoch_ms=200)
                    found = sent.by_digest()
                    for _, _, payload in store.dump():
                        ev = found[traffic.digest(payload)]
                        key = traffic.conversation_key(4, ev.conv)
                        assert decrypt_content(key, payload) == traffic.message_text(ev)
                    assert len(store.dump()) == len(events)
                    return sent

        sent = asyncio.run(main())
        assert sent.accepted == len(events) > 5 and sent.epochs == 51 and clock.now_ms() == 51 * 200

    def test_replay_checks_its_arguments(self) -> None:
        clock = SimClock(start_ms=200)
        with pytest.raises(ValueError, match="time 0"):
            asyncio.run(traffic.replay(None, clock, None, [], seed=1, duration_ms=1000, epoch_ms=200))
        with pytest.raises(ValueError, match="whole number"):
            asyncio.run(traffic.replay(None, SimClock(), None, [], seed=1, duration_ms=1100, epoch_ms=200))
