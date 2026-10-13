"""Comparator-trace invariance of the device sort (M14 S5, experiment E3, the logical half).

The trace of a sort is the sequence of index pairs it compares. `LaunchRecorder` takes it from the
launches the driver actually issues (`kernels.set_launch_hook`): every launch names the (k, j) stages it
performs, and a stage compares the pairs i = (t / j) * 2j + (t % j), l = i + j for t in [0, n/2). The
digest is built the way `oracle.reference.bitonic_sort` builds its trace, so the two can be compared.

What this shows and what it does not: the launch list is a function of n by construction of the
driver, and this records that the driver issued the same list whatever the keys were. It says nothing
about time or about the memory accesses inside a kernel: that is the dudect and SASS work of M08.

`merge_sort_trace` is the seed's data-dependent sort, kept for contrast.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from types import TracebackType
from typing import Any

import numpy as np

from vcloak.gpu import kernels
from vcloak.gpu.engine import GpuEngine, Submission
from vcloak.gpu.runtime import Backend
from vcloak.oracle import reference

# Trace digests are the first 128 bits of a SHA-256: enough to compare traces, and not a 256-bit hex run,
# which is what scripts/check_secrets.py searches the run dirs for.
DIGEST_HEX = 32
INPUTS = ("all-identical", "sorted", "reverse-sorted", "random", "two-value skew")


class LaunchRecorder:
    """Collects (n, launch) of every bitonic launch issued inside the `with` block."""

    def __init__(self) -> None:
        self.launches: list[tuple[int, kernels.Launch]] = []
        self._previous: Any = None

    def __enter__(self) -> LaunchRecorder:
        self._previous = kernels.set_launch_hook(lambda n, launch: self.launches.append((n, launch)))
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        kernels.set_launch_hook(self._previous)

    def stages(self) -> list[tuple[int, int, int]]:
        """(n, k, j) of every stage performed, in order."""
        return [(n, k, j) for n, launch in self.launches for k, j in launch.stages]

    def pair_schedule_sha256(self) -> str:
        """Digest of the pairs compared, stage by stage, in the form of the oracle's trace."""
        return schedule_sha256(self.stages())

    def launch_list_sha256(self) -> str:
        """Digest of the launches themselves (kernel, grid, block, k, j, n)."""
        h = hashlib.sha256()
        for n, launch in self.launches:
            h.update(f"{n}:{launch.kernel}:{launch.grid}:{launch.block}:{launch.k}:{launch.j};".encode())
        return h.hexdigest()[:DIGEST_HEX]


def schedule_sha256(stages: Iterable[tuple[int, int, int]]) -> str:
    h = hashlib.sha256()
    for n, _k, j in stages:
        t = np.arange(n // 2, dtype=np.int64)
        i = (t // j) * 2 * j + (t % j)
        h.update(hashlib.sha256(i.tobytes() + (i + j).tobytes()).digest())
    return h.hexdigest()[:DIGEST_HEX]


def merge_sort_trace(vals: Sequence[int]) -> str:
    """The comparison trace of a conventional merge sort (ported from seed/vcloak_oracle.py)."""
    h = hashlib.sha256()

    def ms(a: list[int], off: int) -> list[int]:
        if len(a) <= 1:
            return a
        m = len(a) // 2
        left, right = ms(a[:m], off), ms(a[m:], off + m)
        out, i, j = [], 0, 0
        while i < len(left) and j < len(right):
            h.update(f"{off + i},{off + m + j};".encode())
            if left[i] <= right[j]:
                out.append(left[i])
                i += 1
            else:
                out.append(right[j])
                j += 1
        return out + left[i:] + right[j:]

    ms(list(vals), 0)
    return h.hexdigest()[:DIGEST_HEX]


def key_vectors(n: int, rng: np.random.Generator) -> dict[str, np.ndarray]:
    """The five key vectors of the oracle's E3."""
    return {
        "all-identical": np.zeros(n, dtype=np.uint64),
        "sorted": np.arange(n, dtype=np.uint64),
        "reverse-sorted": np.arange(n, dtype=np.uint64)[::-1].copy(),
        "random": rng.integers(0, 2**63, n, dtype=np.uint64),
        "two-value skew": (rng.random(n) < 0.95).astype(np.uint64),
    }


def sort_traces(gpu: Backend, n: int, seed: int) -> dict[str, Any]:
    """Sort each input with the device driver and with the oracle; compare the traces and the results."""
    xp = gpu.xp
    rows = []
    for name, v in key_vectors(n, np.random.default_rng(seed)).items():
        idx = np.arange(n, dtype=np.uint64)
        ref_trace: list[bytes] = []
        (ref_keys, _), _ = reference.bitonic_sort([v, idx], trace=ref_trace)
        hi, lo = xp.array(v), xp.zeros(n, dtype=np.uint64)  # a copy: the sort is in place
        slot, pay = xp.arange(n, dtype=np.uint32), xp.arange(n, dtype=np.uint32)
        with LaunchRecorder() as rec:
            kernels.gpu_bitonic_sort(hi, lo, slot, pay)
        got = hi.get() if hasattr(hi, "get") else np.asarray(hi)
        rows.append({"input": name, "launches": len(rec.launches), "stages": len(rec.stages()),
                     "device_trace_sha256": rec.pair_schedule_sha256(),
                     "oracle_trace_sha256": hashlib.sha256(b"".join(ref_trace)).hexdigest()[:DIGEST_HEX],
                     "merge_sort_trace_sha256": merge_sort_trace(v.tolist()),
                     "device_result_equals_oracle": bool(np.array_equal(got, ref_keys))})
    device = {r["device_trace_sha256"] for r in rows}
    merge = {r["merge_sort_trace_sha256"] for r in rows}
    return {"n": n, "seed": seed, "digest": "sha256, first 128 bits", "rows": rows,
            "device_distinct_traces": len(device), "merge_sort_distinct_traces": len(merge),
            "gates": {"device_trace_identical_for_every_input": len(device) == 1,
                      "merge_sort_trace_depends_on_the_input": len(merge) > 1,
                      "device_trace_equals_oracle_trace": all(
                          r["device_trace_sha256"] == r["oracle_trace_sha256"] for r in rows),
                      "device_result_equals_oracle": all(r["device_result_equals_oracle"] for r in rows)}}


def engine_traces(engine: GpuEngine, payload_len: int, seed: int) -> dict[str, Any]:
    """The launches of `write_epoch` for batches that differ in their contents and in their size: the
    list may depend on SLOTS only. The number of real rows is public at the database level."""
    rng = np.random.default_rng(seed)
    slots = engine.slots

    def batch(n_real: int) -> list[Submission]:
        return [Submission(int(rng.integers(1, 2**62)), i, rng.bytes(payload_len)) for i in range(n_real)]

    rows = []
    for name, n_real in (("full, contents A", slots), ("full, contents B", slots), ("half full", slots // 2),
                         ("one row", 1), ("empty", 0)):
        with LaunchRecorder() as rec:
            out = engine.write_epoch(7, batch(n_real))
        rows.append({"batch": name, "n_real": n_real, "rows_out": len(out), "launches": len(rec.launches),
                     "launch_list_sha256": rec.launch_list_sha256(),
                     "pair_schedule_sha256": rec.pair_schedule_sha256()})
    return {"slots": slots, "seed": seed, "rows": rows,
            "gates": {"launch_list_identical_for_every_batch": len({r["launch_list_sha256"] for r in rows}) == 1,
                      "pair_schedule_identical_for_every_batch":
                          len({r["pair_schedule_sha256"] for r in rows}) == 1}}
