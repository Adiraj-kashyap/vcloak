#!/usr/bin/env python3
"""M08 S1-S2 - dudect: does the GPU execution time depend on secret data?

    python bench/run_dudect.py --targets all      --seed 8 [--quick] [--n-per-class N] [--out runs]
    python bench/run_dudect.py --targets controls --seed 8 --quick      # the S1 self-test of the harness

Every target has two input classes: class A is a fixed input, class B is drawn afresh for every
measurement. A run measures exactly N inputs of each class in a random interleaving (N = 10^5, quick
10^4), after a warm-up and a calibration batch that fixes the batch size r and the percentile
thresholds. One measurement is the time between two CUDA events around r launches; r is the same for
both classes and is chosen from public timing only, so that one measurement lasts at least 50 µs.
The preparation of an input is identical for the two classes (the fresh input is drawn for every
measurement and then either used or not), it is finished before the start event, and it is not timed.

Targets (ai/modules/M08 S2)
  bitonic_equal    (a) fused bitonic sort, n = 2^16: all tags equal        vs fresh random tags
  bitonic_sorted   (b) fused bitonic sort, n = 2^16: tags already sorted   vs fresh random tags
  write_epoch      (c) GpuEngine.write_epoch, SLOTS = 2^12, n_real fixed: fixed contents vs fresh random
                       contents. Two series: the device stages (CUDA events of the engine, everything
                       but its `host` stage) and the whole call including the host Python.
  aead_tag         (d) aead_open_seq, 2^16 rows: every tag valid           vs every tag invalid (fresh)
  aead_conv        (e) aead_open_seq, 2^16 rows: every row of conv q       vs no row of conv q
Controls (S1)
  control_leak     a kernel with a planted `if (x) spin(1000)`: zeros vs fresh random. Must be DETECTED.
  control_null     the fused sort with the same fixed input in both classes. Must NOT be detected; a
                   FAIL here means the harness itself separates the classes.

Statistics: vcloak.bench.dudect (Welch t on the raw measurements and on the 100 dudect crops, updated
online; verdict PASS when max |t| < 4.5). Raw measurements go to dudect_<target>_raw.npz, the result
and the t-curve to dudect_<target>.json and .png.

Keys are fixed TEST keys derived from the seed (never production keys).

Diagnostics of ISSUE-17 (group `issue17`; `issue17_rep` is the part repeated with a second seed).
Three series of the M08 job FAIL: aead_conv, aead_tag and the whole write_epoch call. In each of them
the two classes differ in their contents AND in how the harness stages them. These targets separate
the two; none of them replaces a target above.
  aead_conv_null   staging of aead_conv (one fixed host array vs one of a pool), every row of q in BOTH
                   classes. A FAIL here is a difference made by the staging alone (H1).
  aead_conv_swap   aead_conv with the roles swapped: no row of q is the fixed array, every row of q the
                   pool. The sign of t follows either the contents or the staging.
  aead_conv_sym    both classes from pools of the same size, staged on the device before the run and
                   selected by a device-to-device copy. The launch path is that of aead_conv.
  aead_conv_kernel aead_conv_sym with the outputs preallocated and r = 8 launches per measurement: the
                   share of host launch code in the timed window is as small as CuPy allows.
  aead_tag_null    staging of aead_tag (an array the host only read vs one it has just written), every
                   tag valid in BOTH classes (H2).
  aead_tag_swap    aead_tag with the roles swapped: all tags invalid is the fixed array, all valid the
                   freshly written one.
  aead_tag_sym, aead_tag_kernel   as for aead_conv.
  write_epoch_null the same contents in both classes, both batches built from new objects; a class is
                   the batch built first or the one built second, as in write_epoch (H4, build order).
  write_epoch_age  the same contents in both classes; class A is built from long-lived Python ints,
                   class B from new ones, as in write_epoch (H4, object age).
  write_epoch_fresh  fixed vs fresh random contents, both built from new objects, and only the batch
                   that is used is built: the comparison of write_epoch without its staging.

ISSUE-25: two device-stage series of these diagnostics FAIL at seed 8 (write_epoch_age, write_epoch_fresh)
and the cause is not known. `--targets issue25` runs the three diagnostics again with more series of the
same call, so that a FAIL is located in a stage:
  write_epoch_null_st, write_epoch_age_st, write_epoch_fresh_st
                   series device_ms and call_ms as before, core_ms (device_ms without h2d and d2h, the
                   two stages that copy host memory, H5) and one series per stage of the engine.
                   write_epoch_null_st is the control of a run: what it shows is not the contents.

Under the numpy backend (the laptop) each target prepares and runs both classes once at a small size
to check the plumbing and the outputs, and every metric is NOT_MEASURED (ai/GPU_RUNNER.md §3).
"""
from __future__ import annotations

import argparse
import json
import math
import shlex
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chacha_smoke import test_key  # noqa: E402
from vcloak import runs  # noqa: E402
from vcloak.bench import dudect, timing  # noqa: E402
from vcloak.bench.timing import NM  # noqa: E402
from vcloak.gpu import sim, telemetry  # noqa: E402
from vcloak.gpu.engine import STAGES, GpuEngine, Submission  # noqa: E402
from vcloak.gpu.kernels import (  # noqa: E402
    CHACHA_BLOCK,
    SEQ_WORDS,
    SUBKEY_SEQ,
    gpu_bitonic_sort,
    gpu_derive_subkeys,
    gpu_open_and_key,
    gpu_seal_seq,
    subkey,
)
from vcloak.gpu.keystore import DeviceKeyStore  # noqa: E402
from vcloak.gpu.runtime import Backend, get_backend  # noqa: E402

N_FULL, N_QUICK = 100_000, 10_000
CAL_PER_CLASS = 500  # calibration batch: sets r and the crop thresholds, is not part of any test
CHUNK = 1000  # measurements per online update and per point of the t-curve
MIN_MEASUREMENT_MS = 0.050  # ai/GPU_GUIDE.md §7: batch launches if one is under 50 µs
R_PROBE = 30
WARM_MIN_S, WARM_MAX_S = 1.0, 6.0
LOG2N, LOCAL_LOG2N = 16, 8
WRITE_SLOTS, LOCAL_WRITE_SLOTS = 4096, 64
REAL_FRACTION = 4  # n_real = SLOTS / 4, fixed and public
HIT_FRACTION = 8  # aead_tag: one row in 8 belongs to the conversation that is asked for
POOL, POOL_QUICK = 64, 16  # aead_conv: sealed class-B inputs prepared before the run
LEAK_SPINS = 1000
LEAK_SRC = ROOT / "bench" / "planted" / "planted_leak.cu"
SEQ_TAG_WORD = 7  # words 7..10 of a seq_enc row are its tag
EPOCH = 1
KERNEL_WINDOW_R = 8  # launches per measurement of the kernel-only targets (ISSUE-17)
TELEMETRY_HZ = 2.0
CONTROLS = ("control_leak", "control_null")
SHARED_GPU_CAVEAT = ("Free Colab/Kaggle GPUs are shared: a PASS says that no dependence was detected with this "
                     "many measurements on this device in this session, not that none exists.")


def put(dev: Any, host: np.ndarray) -> None:
    """Upload `host` into the device array `dev` (a plain copy on the simulator)."""
    if hasattr(dev, "set"):
        dev.set(host)
    else:
        dev[...] = host


def to_host(a: Any) -> np.ndarray:
    return a if type(a) is np.ndarray else (a.get() if hasattr(a, "get") else np.asarray(a))


class Target:
    """One dudect target. `prepare` puts the input of a class on the device and is never timed; `run`
    is the timed work and receives nothing: its launches are a function of public sizes only."""

    name = ""
    metric = ""
    title = ""
    class0 = ""
    class1 = ""
    in_place = False  # the work overwrites its input: r launches cannot be batched in one measurement
    series: tuple[str, ...] = ("ms",)
    expect = dudect.PASS  # controls: the verdict that shows the harness works
    min_r = 1  # at least this many launches per measurement (public)

    def prepare(self, cls: int, rng: np.random.Generator) -> None:
        raise NotImplementedError

    def run(self) -> None:
        raise NotImplementedError

    def check(self, cls: int) -> int:
        """Number of wrong output elements after a run on an input of class `cls`."""
        raise NotImplementedError

    def measure(self, cp: Any, stream: Any, start: Any, end: Any, r: int) -> tuple[float, ...]:
        """One measurement in ms per series: r launches between two CUDA events on `stream`."""
        stream.synchronize()  # the uploads of `prepare` are finished and outside the timed region
        start.record(stream)
        for _ in range(r):
            self.run()
        end.record(stream)
        end.synchronize()
        return (float(cp.cuda.get_elapsed_time(start, end)),)

    def params(self) -> dict[str, Any]:
        return {}


class _Bitonic(Target):
    in_place = True

    def __init__(self, backend: Backend, n: int, seed: int) -> None:
        xp = backend.xp
        self.n = n
        self.cols = (xp.empty(n, dtype=np.uint64), xp.empty(n, dtype=np.uint64),
                     xp.empty(n, dtype=np.uint32), xp.empty(n, dtype=np.uint32))
        self.ident = np.arange(n, dtype=np.uint32)
        self.fixed = self.fixed_input(np.random.default_rng([seed, n, 100]))
        self.last: tuple[np.ndarray, np.ndarray] = self.fixed

    def fixed_input(self, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
        raise NotImplementedError

    def fresh(self, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
        return (rng.integers(0, 2**64, self.n, dtype=np.uint64), rng.integers(0, 2**64, self.n, dtype=np.uint64))

    def prepare(self, cls: int, rng: np.random.Generator) -> None:
        fresh = self.fresh(rng)  # drawn for both classes: the host does the same work before every measurement
        self.last = fresh if cls else self.fixed
        put(self.cols[0], self.last[0])
        put(self.cols[1], self.last[1])
        put(self.cols[2], self.ident)
        put(self.cols[3], self.ident)

    def run(self) -> None:
        gpu_bitonic_sort(*self.cols)

    def check(self, cls: int) -> int:  # noqa: ARG002
        hi, lo = self.last
        order = np.lexsort((self.ident, lo, hi)).astype(np.uint32)  # host reference of public test data
        got = [to_host(c) for c in self.cols]
        return int(np.count_nonzero(got[0] != hi[order]) + np.count_nonzero(got[1] != lo[order])
                   + np.count_nonzero(got[2] != order) + np.count_nonzero(got[3] != order))

    def params(self) -> dict[str, Any]:
        return {"n": self.n, "kernel": "gpu_bitonic_sort (fused launch plan)"}


class BitonicEqual(_Bitonic):
    name, metric = "bitonic_equal", "BITONIC-EQUAL"
    title = "(a) fused bitonic sort: all-equal tags vs random tags"
    class0, class1 = "every (hi, lo) tag equal (fixed)", "fresh uniform random (hi, lo) tags"

    def fixed_input(self, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
        hi, lo = (int(v) for v in rng.integers(0, 2**64, 2, dtype=np.uint64))
        return np.full(self.n, hi, dtype=np.uint64), np.full(self.n, lo, dtype=np.uint64)


class BitonicSorted(_Bitonic):
    name, metric = "bitonic_sorted", "BITONIC-SORTED"
    title = "(b) fused bitonic sort: sorted tags vs random tags"
    class0, class1 = "tags already in sorted order (fixed)", "fresh uniform random (hi, lo) tags"

    def fixed_input(self, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
        hi = np.sort(rng.integers(0, 2**64, self.n, dtype=np.uint64))
        return hi, rng.integers(0, 2**64, self.n, dtype=np.uint64)


class ControlNull(BitonicSorted):
    name, metric = "control_null", "CONTROL-NULL"
    title = "null control: fused bitonic sort, the same fixed input in both classes"
    class0, class1 = "fixed sorted tags", "the same fixed sorted tags"

    def prepare(self, cls: int, rng: np.random.Generator) -> None:
        super().prepare(0, rng)  # the class label is the only difference


class ControlLeak(Target):
    name, metric, expect = "control_leak", "CONTROL-LEAK", dudect.FAIL
    title = f"positive control: planted `if (x) spin({LEAK_SPINS})` kernel, zeros vs random"
    class0, class1 = "x = 0 everywhere (fixed)", "fresh uniform random x"

    def __init__(self, backend: Backend, n: int, seed: int) -> None:  # noqa: ARG002
        xp = backend.xp
        self.n = n
        self.x, self.out = xp.empty(n, dtype=np.uint32), xp.empty(n, dtype=np.uint32)
        self.zeros = np.zeros(n, dtype=np.uint32)
        self.last = self.zeros
        self.block = min(CHACHA_BLOCK, n)
        self.grid = -(-n // self.block)
        self.fn = None
        if not isinstance(self.x, np.ndarray):
            self.fn = xp.RawModule(code=LEAK_SRC.read_text(encoding="utf-8"),
                                   options=("-std=c++17",)).get_function("planted_leak")

    def prepare(self, cls: int, rng: np.random.Generator) -> None:
        fresh = rng.integers(0, 2**32, self.n, dtype=np.uint32)
        self.last = fresh if cls else self.zeros
        put(self.x, self.last)

    def run(self) -> None:
        if self.fn is None:
            sim.get("planted_leak")(self.x, self.out, self.n, LEAK_SPINS, grid=self.grid, block=self.block)
        else:
            self.fn((self.grid,), (self.block,), (self.x, self.out, np.uint32(self.n), np.uint32(LEAK_SPINS)))

    def check(self, cls: int) -> int:  # noqa: ARG002
        want = np.empty(self.n, dtype=np.uint32)
        sim.get("planted_leak")(self.last, want, self.n, LEAK_SPINS, grid=self.grid, block=self.block)
        return int(np.count_nonzero(to_host(self.out) != want))

    def params(self) -> dict[str, Any]:
        return {"n": self.n, "spins": LEAK_SPINS, "kernel": "bench/planted/planted_leak.cu"}


class _AeadOpen(Target):
    def __init__(self, backend: Backend, n: int, seed: int) -> None:
        xp = self.xp = backend.xp
        self.n = n
        master = np.frombuffer(test_key(seed), dtype="<u4").astype(np.uint32)
        self.kseq = subkey(gpu_derive_subkeys(xp.asarray(master)), SUBKEY_SEQ)
        self.blobs = xp.empty(SEQ_WORDS * n, dtype=np.uint32)
        self.out: tuple[Any, Any, Any] | None = None
        self.q = 0

    def seal(self, conv: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        """Valid seq_enc rows for the given conversation ids, as host words (public ciphertext)."""
        xp = self.xp
        seq = rng.integers(0, 2**64, self.n, dtype=np.uint64)
        nonces = rng.integers(0, 2**32, 3 * self.n, dtype=np.uint32)
        return to_host(gpu_seal_seq(self.kseq, xp.asarray(conv), xp.asarray(seq), xp.asarray(nonces))).copy()

    def run(self) -> None:
        self.out = gpu_open_and_key(self.kseq, self.blobs, self.q)

    def params(self) -> dict[str, Any]:
        return {"rows": self.n, "kernel": "aead_open_seq"}


class AeadTag(_AeadOpen):
    name, metric = "aead_tag", "AEAD-TAG"
    title = "(d) AEAD open: all tags valid vs all tags invalid"
    class0 = "every row authentic, one row in 8 of the conversation asked for (fixed)"
    class1 = "the same rows with fresh random tag words (every tag invalid)"

    def __init__(self, backend: Backend, n: int, seed: int) -> None:
        super().__init__(backend, n, seed)
        rng = np.random.default_rng([seed, n, 200])
        conv = rng.integers(0, 2**64, n, dtype=np.uint64)
        conv[: max(1, n // HIT_FRACTION)] = conv[0]
        self.q = int(conv[0])
        self.valid = self.seal(conv, rng)
        self.hits = int(np.count_nonzero(conv == conv[0]))

    def tags(self, rows: np.ndarray) -> np.ndarray:
        """The tag words of host rows, as a view."""
        return rows.reshape(self.n, SEQ_WORDS)[:, SEQ_TAG_WORD:]

    def prepare(self, cls: int, rng: np.random.Generator) -> None:
        fresh = self.valid.copy()
        self.tags(fresh)[...] = rng.integers(0, 2**32, (self.n, 4), dtype=np.uint32)
        put(self.blobs, fresh if cls else self.valid)

    def is_valid(self, cls: int) -> bool:
        return not cls

    def check(self, cls: int) -> int:
        hi, _lo, ok = (to_host(a) for a in self.out)  # type: ignore[union-attr]
        if not self.is_valid(cls):
            return int(np.count_nonzero(ok != 0) + np.count_nonzero(hi != 1))
        return int(np.count_nonzero(ok != 1) + abs(int(np.count_nonzero(hi == 0)) - self.hits))


class AeadTagNull(AeadTag):
    name, metric = "aead_tag_null", "AEAD-TAG-NULL"
    title = "ISSUE-17 (d) staging only: all tags valid in both classes, read-only array vs freshly written array"
    class0 = "every row authentic: the fixed host array, only ever read"
    class1 = "the same rows and the same valid tags, in a host array written just before the upload"

    def prepare(self, cls: int, rng: np.random.Generator) -> None:
        fresh = self.valid.copy()
        rng.integers(0, 2**32, (self.n, 4), dtype=np.uint32)  # drawn as in aead_tag, not used
        self.tags(fresh)[...] = self.tags(self.valid)
        put(self.blobs, fresh if cls else self.valid)

    def is_valid(self, cls: int) -> bool:  # noqa: ARG002
        return True


class AeadTagSwap(AeadTag):
    name, metric = "aead_tag_swap", "AEAD-TAG-SWAP"
    title = "ISSUE-17 (d) roles swapped: all tags invalid (fixed array) vs all tags valid (freshly written array)"
    class0 = "every tag invalid: a fixed host array, only ever read"
    class1 = "the same rows with their valid tags, in a host array written just before the upload"

    def __init__(self, backend: Backend, n: int, seed: int) -> None:
        super().__init__(backend, n, seed)
        self.invalid = self.valid.copy()
        self.tags(self.invalid)[...] = np.random.default_rng([seed, n, 201]).integers(0, 2**32, (n, 4),
                                                                                      dtype=np.uint32)

    def prepare(self, cls: int, rng: np.random.Generator) -> None:
        fresh = self.invalid.copy()
        rng.integers(0, 2**32, (self.n, 4), dtype=np.uint32)  # drawn as in aead_tag, not used
        self.tags(fresh)[...] = self.tags(self.valid)
        put(self.blobs, fresh if cls else self.invalid)

    def is_valid(self, cls: int) -> bool:
        return bool(cls)


class _DevicePools:
    """Symmetric staging (ISSUE-17): each class has a pool of the same number of inputs, on the device
    before the run. Preparing an input is one index drawn for both classes and one device-to-device copy."""

    pools: tuple[list[Any], list[Any]]

    def prepare(self, cls: int, rng: np.random.Generator) -> None:
        i = int(rng.integers(0, len(self.pools[0])))
        self.xp.copyto(self.blobs, self.pools[cls][i])  # type: ignore[attr-defined]

    def params(self) -> dict[str, Any]:
        return {**super().params(), "pool_per_class": len(self.pools[0]),  # type: ignore[misc]
                "staging": "device pools, device-to-device copy"}


class _KernelWindow:
    """Kernel-only window (ISSUE-17): the outputs exist before the run and one measurement is
    KERNEL_WINDOW_R launches, so the timed region holds as little host code as the launch path allows."""

    min_r = KERNEL_WINDOW_R

    def run(self) -> None:
        if self.out is None:  # type: ignore[has-type]
            xp, n = self.xp, self.n  # type: ignore[attr-defined]
            self.out = (xp.empty(n, dtype=np.uint64), xp.empty(n, dtype=np.uint64), xp.empty(n, dtype=np.uint32))
        gpu_open_and_key(self.kseq, self.blobs, self.q, out=self.out)  # type: ignore[attr-defined]

    def params(self) -> dict[str, Any]:
        return {**super().params(), "outputs": "preallocated", "min_r": self.min_r}  # type: ignore[misc]


class AeadTagSym(_DevicePools, AeadTag):
    name, metric = "aead_tag_sym", "AEAD-TAG-SYM"
    title = "ISSUE-17 (d) symmetric staging: all tags valid vs all tags invalid, device pools"
    class0 = "every row authentic, one row in 8 of the conversation asked for (one of a device pool)"
    class1 = "the same rows with random tag words, every tag invalid (one of a device pool of the same size)"

    def __init__(self, backend: Backend, n: int, seed: int, pool: int = POOL) -> None:
        super().__init__(backend, n, seed)
        rng = np.random.default_rng([seed, n, 210])
        conv = rng.integers(0, 2**64, n, dtype=np.uint64)
        conv[conv == np.uint64(self.q)] ^= np.uint64(1)  # public test data
        conv[: self.hits] = np.uint64(self.q)
        self.pools = ([], [])
        for _ in range(pool):
            rows = self.seal(conv, rng)
            self.pools[0].append(self.xp.asarray(rows.copy()))  # a host array is not copied by asarray
            self.tags(rows)[...] = rng.integers(0, 2**32, (n, 4), dtype=np.uint32)
            self.pools[1].append(self.xp.asarray(rows))


class AeadTagKernel(_KernelWindow, AeadTagSym):
    name, metric = "aead_tag_kernel", "AEAD-TAG-KERNEL"
    title = "ISSUE-17 (d) kernel-only window: all tags valid vs all invalid, device pools, preallocated outputs"


class AeadConv(_AeadOpen):
    name, metric = "aead_conv", "AEAD-CONV"
    title = "(e) AEAD open: every row matches q vs no row matches q"
    class0 = "every row authentic and of conversation q (fixed)"
    class1 = "every row authentic, random conversations != q (one of a pool of sealed inputs, chosen afresh)"

    def __init__(self, backend: Backend, n: int, seed: int, pool: int = POOL) -> None:
        super().__init__(backend, n, seed)
        rng = np.random.default_rng([seed, n, 300])
        self.q = int(rng.integers(1, 2**63, dtype=np.uint64))
        self.match = self.seal(self.conv(self.hit[0], rng), rng)  # the fixed input of class A
        self.pool = [self.seal(self.conv(self.hit[1], rng), rng) for _ in range(pool)]

    hit = (True, False)  # per class: does every row belong to conversation q?

    def conv(self, hit: bool, rng: np.random.Generator) -> np.ndarray:
        if hit:
            return np.full(self.n, self.q, dtype=np.uint64)
        conv = rng.integers(0, 2**64, self.n, dtype=np.uint64)
        conv[conv == np.uint64(self.q)] ^= np.uint64(1)  # public test data: never q
        return conv

    def prepare(self, cls: int, rng: np.random.Generator) -> None:
        other = self.pool[int(rng.integers(0, len(self.pool)))]
        put(self.blobs, other if cls else self.match)

    def check(self, cls: int) -> int:
        hi, _lo, ok = (to_host(a) for a in self.out)  # type: ignore[union-attr]
        return int(np.count_nonzero(ok != 1) + np.count_nonzero(hi != (0 if self.hit[cls] else 1)))

    def params(self) -> dict[str, Any]:
        return {**super().params(), "class1_pool": len(self.pool)}


class AeadConvNull(AeadConv):
    name, metric = "aead_conv_null", "AEAD-CONV-NULL"
    title = "ISSUE-17 (e) staging only: every row matches q in both classes, fixed array vs pool"
    class0 = "every row authentic and of conversation q (one fixed host array)"
    class1 = "every row authentic and of conversation q (one of a pool of sealed inputs, chosen afresh)"
    hit = (True, True)


class AeadConvSwap(AeadConv):
    name, metric = "aead_conv_swap", "AEAD-CONV-SWAP"
    title = "ISSUE-17 (e) roles swapped: no row matches q (fixed array) vs every row matches q (pool)"
    class0 = "every row authentic, random conversations != q (one fixed host array)"
    class1 = "every row authentic and of conversation q (one of a pool of sealed inputs, chosen afresh)"
    hit = (False, True)


class AeadConvSym(_DevicePools, AeadConv):
    name, metric = "aead_conv_sym", "AEAD-CONV-SYM"
    title = "ISSUE-17 (e) symmetric staging: every row matches q vs no row matches q, device pools"
    class0 = "every row authentic and of conversation q (one of a device pool)"
    class1 = "every row authentic, random conversations != q (one of a device pool of the same size)"

    def __init__(self, backend: Backend, n: int, seed: int, pool: int = POOL) -> None:
        super().__init__(backend, n, seed, pool=0)
        rng = np.random.default_rng([seed, n, 310])
        self.pools = ([self.xp.asarray(self.seal(self.conv(True, rng), rng)) for _ in range(pool)],
                      [self.xp.asarray(self.seal(self.conv(False, rng), rng)) for _ in range(pool)])

    def params(self) -> dict[str, Any]:
        p = super().params()
        del p["class1_pool"]
        return p


class AeadConvKernel(_KernelWindow, AeadConvSym):
    name, metric = "aead_conv_kernel", "AEAD-CONV-KERNEL"
    title = "ISSUE-17 (e) kernel-only window: every row matches q vs none, device pools, preallocated outputs"


class WriteEpoch(Target):
    name, metric = "write_epoch", "WRITE-EPOCH"
    title = "(c) write_epoch: fixed contents vs random contents, n_real fixed"
    class0 = "the same (conv_id, seq, payload) submissions every time (fixed)"
    class1 = "fresh random conv_id, seq and payload for every submission"
    series = ("device_ms", "call_ms")
    in_place = True  # one call is one measurement: the engine times itself, calls are never batched

    def __init__(self, backend: Backend, slots: int, seed: int) -> None:
        self.slots, self.n_real = slots, slots // REAL_FRACTION
        store = DeviceKeyStore(backend)
        store.load_master(bytearray(test_key(seed)))
        self.eng = GpuEngine(store, slots)
        self.fixed = self.contents(np.random.default_rng([seed, slots, 400]))
        self.batch: list[Submission] = []
        self.rows: list[Any] = []

    def contents(self, rng: np.random.Generator) -> tuple[list[int], list[int], bytes]:
        return (rng.integers(0, 2**64, self.n_real, dtype=np.uint64).tolist(),
                rng.integers(0, 2**64, self.n_real, dtype=np.uint64).tolist(), rng.bytes(8 * self.n_real))

    @staticmethod
    def build(contents: tuple[list[int], list[int], bytes]) -> list[Submission]:
        conv, seq, pay = contents
        return [Submission(c, s, pay[8 * i:8 * i + 8]) for i, (c, s) in enumerate(zip(conv, seq, strict=True))]

    def prepare(self, cls: int, rng: np.random.Generator) -> None:
        both = (self.build(self.fixed), self.build(self.contents(rng)))  # new objects for both classes
        self.batch = both[cls]

    def run(self) -> None:
        self.rows = self.eng.write_epoch(EPOCH, self.batch)

    def measure(self, cp: Any, stream: Any, start: Any, end: Any, r: int) -> tuple[float, ...]:  # noqa: ARG002
        self.run()
        t = self.eng.last_timings()  # CUDA events on the engine's own stream
        return (t["total"] - t["host"], t["total"])

    def check(self, cls: int) -> int:  # noqa: ARG002
        want = sorted(s.payload for s in self.batch)
        return abs(len(self.rows) - self.n_real) + int(sorted(r.payload for r in self.rows) != want)

    def params(self) -> dict[str, Any]:
        return {"slots": self.slots, "n_real": self.n_real, "epoch": EPOCH, "timer": self.eng.timer,
                "device_ms": "total minus the engine's host stage; stages: " + ", ".join(STAGES)}


class _WriteEpochDiag(WriteEpoch):
    def __init__(self, backend: Backend, slots: int, seed: int) -> None:
        super().__init__(backend, slots, seed)
        self.fixed_seed = [seed, slots, 400]

    def fixed_again(self) -> tuple[list[int], list[int], bytes]:
        """The fixed contents of class A, value for value, as new Python objects."""
        return self.contents(np.random.default_rng(self.fixed_seed))


class WriteEpochNull(_WriteEpochDiag):
    name, metric = "write_epoch_null", "WRITE-EPOCH-NULL"
    title = "ISSUE-17 (c) staging only: the same contents in both classes, new objects, built first vs built second"
    class0 = "the fixed submissions, rebuilt from new objects; the batch built first"
    class1 = "the same fixed submissions, rebuilt from new objects; the batch built second"

    def prepare(self, cls: int, rng: np.random.Generator) -> None:
        self.contents(rng)  # drawn as in write_epoch, not used
        both = (self.build(self.fixed_again()), self.build(self.fixed_again()))
        self.batch = both[cls]


class WriteEpochAge(_WriteEpochDiag):
    name, metric = "write_epoch_age", "WRITE-EPOCH-AGE"
    title = "ISSUE-17 (c) staging only: the same contents in both classes, long-lived objects vs new objects"
    class0 = "the fixed submissions, built from the long-lived Python ints of the target"
    class1 = "the same fixed submissions, built from Python ints created just before the call"

    def prepare(self, cls: int, rng: np.random.Generator) -> None:
        self.contents(rng)  # drawn as in write_epoch, not used
        both = (self.build(self.fixed), self.build(self.fixed_again()))
        self.batch = both[cls]


class WriteEpochFresh(_WriteEpochDiag):
    name, metric = "write_epoch_fresh", "WRITE-EPOCH-FRESH"
    title = "ISSUE-17 (c) symmetric staging: fixed contents vs random contents, new objects, one batch built"
    class0 = "the fixed submissions, rebuilt from new objects before every call"
    class1 = "fresh random conv_id, seq and payload for every submission"

    def prepare(self, cls: int, rng: np.random.Generator) -> None:
        both = (self.fixed_again(), self.contents(rng))  # both drawn, so the host does the same work
        self.batch = self.build(both[cls])  # the only batch, built last for either class


# ISSUE-25: where in the device stages does a write_epoch series separate the classes?
WRITE_STAGES = tuple(s for s in STAGES if s not in ("host", "open"))  # `open` is a read stage: never marked here
TRANSFER_STAGES = ("h2d", "d2h")  # they copy host memory that `prepare` built (H5)
STAGE_SERIES = ("device_ms", "call_ms", "core_ms", *(f"{s}_ms" for s in WRITE_STAGES))


class _StageSeries:
    """ISSUE-25: the same call and the same staging as the parent target, with every stage of the engine
    as its own series and `core_ms`, the device stages without the two transfers. One call gives all of
    them, so the series of a target are not independent tests. A stage is not batched: one that lasts
    less than MIN_MEASUREMENT_MS is quoted with its median, and is read with that in mind."""

    series = STAGE_SERIES

    def measure(self, cp: Any, stream: Any, start: Any, end: Any, r: int) -> tuple[float, ...]:  # noqa: ARG002
        self.run()  # type: ignore[attr-defined]
        t = self.eng.last_timings()  # type: ignore[attr-defined]
        device = t["total"] - t["host"]
        return (device, t["total"], device - sum(t[s] for s in TRANSFER_STAGES), *(t[s] for s in WRITE_STAGES))

    def params(self) -> dict[str, Any]:
        return super().params() | {  # type: ignore[misc]
            "core_ms": "device_ms minus the stages " + ", ".join(TRANSFER_STAGES),
            "stage_series": "one series per engine stage: " + ", ".join(WRITE_STAGES) + "; not batched",
            "series_of_one_call": len(STAGE_SERIES)}


class WriteEpochNullSt(_StageSeries, WriteEpochNull):
    name, metric = "write_epoch_null_st", "WRITE-EPOCH-NULL-ST"
    title = "ISSUE-25 per stage, staging only: the same contents in both classes, built first vs built second"


class WriteEpochAgeSt(_StageSeries, WriteEpochAge):
    name, metric = "write_epoch_age_st", "WRITE-EPOCH-AGE-ST"
    title = "ISSUE-25 per stage, staging only: the same contents in both classes, long-lived vs new objects"


class WriteEpochFreshSt(_StageSeries, WriteEpochFresh):
    name, metric = "write_epoch_fresh_st", "WRITE-EPOCH-FRESH-ST"
    title = "ISSUE-25 per stage, symmetric staging: fixed contents vs random contents, one batch built"


DIAG_CLASSES = (AeadConvNull, AeadConvSwap, AeadConvSym, AeadConvKernel, AeadTagNull, AeadTagSwap, AeadTagSym,
                AeadTagKernel, WriteEpochNull, WriteEpochAge, WriteEpochFresh,
                WriteEpochNullSt, WriteEpochAgeSt, WriteEpochFreshSt)


def build_target(name: str, backend: Backend, seed: int, quick: bool) -> Target:
    lg = LOG2N if backend.is_gpu else LOCAL_LOG2N
    n = 1 << lg
    if name == "bitonic_equal":
        return BitonicEqual(backend, n, seed)
    if name == "bitonic_sorted":
        return BitonicSorted(backend, n, seed)
    if name == "control_null":
        return ControlNull(backend, n, seed)
    if name == "control_leak":
        return ControlLeak(backend, n, seed)
    if name == "aead_tag":
        return AeadTag(backend, n, seed)
    if name == "aead_conv":
        return AeadConv(backend, n, seed, pool=(POOL_QUICK if quick else POOL) if backend.is_gpu else 2)
    if name == "write_epoch":
        return WriteEpoch(backend, WRITE_SLOTS if backend.is_gpu else LOCAL_WRITE_SLOTS, seed)
    pool = (POOL_QUICK if quick else POOL) if backend.is_gpu else 2
    for cls in DIAG_CLASSES:
        if cls.name != name:
            continue
        if issubclass(cls, WriteEpoch):
            return cls(backend, WRITE_SLOTS if backend.is_gpu else LOCAL_WRITE_SLOTS, seed)
        if issubclass(cls, (AeadConv, _DevicePools)):
            return cls(backend, n, seed, pool=pool)
        return cls(backend, n, seed)
    raise ValueError(f"unknown target {name!r}")


TARGETS = ("bitonic_equal", "bitonic_sorted", "write_epoch", "aead_tag", "aead_conv")
ALL = (*CONTROLS, *TARGETS)
METRIC_OF = {"bitonic_equal": "BITONIC-EQUAL", "bitonic_sorted": "BITONIC-SORTED", "write_epoch": "WRITE-EPOCH",
             "aead_tag": "AEAD-TAG", "aead_conv": "AEAD-CONV", "control_leak": "CONTROL-LEAK",
             "control_null": "CONTROL-NULL"}
# ISSUE-17: the failing M08 targets and their diagnostics. Not part of `all` or `targets`.
DIAG = tuple(c.name for c in DIAG_CLASSES)
ISSUE17 = ("aead_conv", "aead_conv_null", "aead_conv_swap", "aead_conv_sym", "aead_conv_kernel",
           "aead_tag", "aead_tag_null", "aead_tag_swap", "aead_tag_sym", "aead_tag_kernel",
           "write_epoch", "write_epoch_null", "write_epoch_age", "write_epoch_fresh")
ISSUE17_REP = tuple(n for n in ISSUE17 if n not in ("write_epoch_null", "write_epoch_age"))
# ISSUE-25: the control first, so a FAIL of the other two is read against it in the same run.
ISSUE25 = ("write_epoch_null_st", "write_epoch_age_st", "write_epoch_fresh_st")
KNOWN = (*ALL, *DIAG)
METRIC_OF.update({c.name: c.metric for c in DIAG_CLASSES})
SERIES_SUFFIX = {"ms": "", "device_ms": "", "call_ms": "-CALL", "core_ms": "-CORE",
                 **{f"{s}_ms": f"-{s.upper()}" for s in WRITE_STAGES}}


def choose_r(single_ms: list[float], in_place: bool) -> tuple[int, str]:
    """The public batch size: enough launches for one measurement to last MIN_MEASUREMENT_MS, from the
    median time of single launches over inputs of both classes. In-place work cannot be batched."""
    med = float(np.median(single_ms))
    want = max(1, math.ceil(MIN_MEASUREMENT_MS / med)) if med > 0 else 1
    if want > 1 and in_place:
        return 1, (f"one launch takes {med * 1e3:.1f} us (median), below {MIN_MEASUREMENT_MS * 1e3:.0f} us, "
                   "and the work is in place: not batched")
    return want, ""


def run_target(t: Target, backend: Backend, n_per_class: int, seed: int, run_dir: Path,
               sample: Any = None, log: Any = print) -> dict[str, Any]:
    """Warm up, calibrate, measure 2 * n_per_class inputs in a random interleaving, test online, save."""
    sample = sample or telemetry.sample
    cp = backend.xp
    stream = cp.cuda.get_current_stream()
    start, end = cp.cuda.Event(), cp.cuda.Event()
    rng = np.random.default_rng([seed, 1])  # inputs
    order_rng = np.random.default_rng([seed, 2])  # class order: independent of the inputs

    def one(cls: int, r: int) -> tuple[float, ...]:
        t.prepare(cls, rng)
        return t.measure(cp, stream, start, end, r)

    def spin() -> None:
        one(int(order_rng.integers(0, 2)), 1)

    warm = timing.warm_until_stable(spin, min_calls=10, snapshot=sample, sync=stream.synchronize,
                                    min_seconds=WARM_MIN_S, max_seconds=WARM_MAX_S)
    probe = [one(i % 2, 1)[0] for i in range(R_PROBE)]
    r, r_note = choose_r(probe, t.in_place)
    if r < t.min_r:
        r, r_note = t.min_r, f"{t.min_r} launches per measurement by design (public), not from the 50 us rule"

    bad = 0
    for cls in (0, 1):  # the output of each class is checked once, outside the measurements
        t.prepare(cls, rng)
        stream.synchronize()
        t.run()
        stream.synchronize()
        bad += t.check(cls)

    cal_classes = dudect.balanced_classes(CAL_PER_CLASS, order_rng)
    cal = np.array([one(int(c), r) for c in cal_classes], dtype=np.float64)
    tests = [dudect.OnlineTTest(dudect.crop_thresholds(cal[:, s])) for s in range(len(t.series))]

    classes = dudect.balanced_classes(n_per_class, order_rng)
    times = np.empty((classes.size, len(t.series)), dtype=np.float64)
    clock_before = sample()
    t0 = time.monotonic()
    for lo in range(0, classes.size, CHUNK):
        hi = min(lo + CHUNK, classes.size)
        for i in range(lo, hi):
            times[i] = one(int(classes[i]), r)
        for s, test in enumerate(tests):
            test.update(times[lo:hi, s], classes[lo:hi])
            test.checkpoint()
        if hi == classes.size or (hi // CHUNK) % max(1, classes.size // CHUNK // 10) == 0:
            log(f"  {t.name}: {hi}/{classes.size}  max|t| "
                + "  ".join(f"{name} {test.max_abs_t()[0]:.3f}" for name, test in zip(t.series, tests, strict=True)))
    seconds = time.monotonic() - t0
    clock = timing.clock_check(clock_before, sample())

    np.savez_compressed(run_dir / f"dudect_{t.name}_raw.npz", times_ms=times, classes=classes,
                        calibration_ms=cal, calibration_classes=cal_classes, series=np.array(t.series), r=r)
    out: dict[str, Any] = {
        "target": t.name, "title": t.title, "class0": t.class0, "class1": t.class1, "params": t.params(),
        "n_per_class": n_per_class, "calibration_per_class": CAL_PER_CLASS, "chunk": CHUNK, "r": r, "r_note": r_note,
        "single_launch_median_ms": float(np.median(probe)), "measure_seconds": seconds, "mismatches": bad,
        "expected_verdict": t.expect, "warmup": {k: warm[k] for k in ("calls", "seconds", "clocks_mhz")},
        "clock": clock, "timer": "cupy.cuda.Event", "series": {},
        "raw": f"dudect_{t.name}_raw.npz", "plots": [],
    }
    for s, (name, test) in enumerate(zip(t.series, tests, strict=True)):
        res = test.result()
        res["summary_class0"] = timing.summarise(times[classes == 0, s])
        res["summary_class1"] = timing.summarise(times[classes == 1, s])
        res["curve"] = test.curve
        out["series"][name] = res
        png = f"dudect_{t.name}" + ("" if s == 0 else f"_{name}") + ".png"
        try:
            dudect.plot_curve(run_dir / png, test.curve,
                              f"{t.title}\n{name}, N = {n_per_class} per class, r = {r}, max |t| = "
                              f"{res['max_abs_t']:.3f} ({res['verdict']})")
            out["plots"].append(png)
        except Exception as e:  # noqa: BLE001 - a missing matplotlib must not lose the measurements
            out.setdefault("plot_errors", []).append(f"{png}: {type(e).__name__}: {e}"[:200])
    primary = out["series"][t.series[0]]
    out["max_abs_t"], out["verdict"] = primary["max_abs_t"], primary["verdict"]
    (run_dir / f"dudect_{t.name}.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    return out


def plumbing(t: Target, seed: int) -> dict[str, Any]:
    """numpy backend: prepare and run each class once, check the outputs, measure nothing."""
    rng = np.random.default_rng([seed, 1])
    bad = 0
    for cls in (0, 1):
        t.prepare(cls, rng)
        t.run()
        bad += t.check(cls)
    return {"target": t.name, "title": t.title, "class0": t.class0, "class1": t.class1, "params": t.params(),
            "mismatches": bad, "verdict": NM, "expected_verdict": t.expect}


def metric(mid: str, value: Any, unit: str, stat: str, note: str) -> dict[str, Any]:
    return {"id": mid, "value": value, "unit": unit, "stat": stat, "note": note}


def metrics_of(results: list[dict[str, Any]], quick: bool, reason: str | None) -> list[dict[str, Any]]:
    out = []
    tag = " (quick)" if quick else ""
    for res in results:
        base = METRIC_OF[res["target"]]
        if reason:
            out.append(metric(f"T-DUDECT-MAXT-{base}", NM, "-", "max |t|", reason))
            out.append(metric(f"T-DUDECT-N-{base}", NM, "measurements", "per class", reason))
            continue
        for name, s in res["series"].items():
            sfx = SERIES_SUFFIX[name]
            note = (f"{s['verdict']} at threshold {s['threshold']}{tag}; max at {s['max_at']}; Welch t, raw + "
                    f"{s['tests'] - 1} crops; series {name}; r {res['r']}")
            value = round(s["max_abs_t"], 4) if math.isfinite(s["max_abs_t"]) else "inf"
            out.append(metric(f"T-DUDECT-MAXT-{base}{sfx}", value, "-", "max |t|", note))
        out.append(metric(f"T-DUDECT-N-{base}", res["n_per_class"], "measurements", "per class",
                          f"exactly this many of each class, randomly interleaved{tag}"))
    return out


def parse_targets(text: str) -> list[str]:
    names: list[str] = []
    for part in text.split(","):
        part = part.strip()
        group = {"all": ALL, "controls": CONTROLS, "targets": TARGETS, "issue17": ISSUE17,
                 "issue17_rep": ISSUE17_REP, "issue25": ISSUE25}.get(part, (part,))
        for name in group:
            if name not in KNOWN:
                raise SystemExit(f"unknown target {name!r}; choose from: all, controls, targets, issue17, "
                                 f"issue17_rep, issue25, {', '.join(KNOWN)}")
            if name not in names:
                names.append(name)
    return names


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--targets", default="all", help="comma list of: all, controls, targets, issue17, issue17_rep, "
                    "issue25, " + ", ".join(KNOWN))
    ap.add_argument("--seed", type=int, default=8)
    ap.add_argument("--quick", action="store_true", help=f"N = {N_QUICK} per class instead of {N_FULL}")
    ap.add_argument("--n-per-class", type=int, default=0, help="override N (recorded in the manifest)")
    ap.add_argument("--name", default="dudect", help="run dir name suffix")
    ap.add_argument("--out", default="runs")
    a = ap.parse_args(argv)
    names = parse_targets(a.targets)
    n_per_class = a.n_per_class or (N_QUICK if a.quick else N_FULL)
    command = "python bench/run_dudect.py " + " ".join(shlex.quote(x) for x in (argv if argv is not None
                                                                              else sys.argv[1:]))
    backend = get_backend()
    run_dir = runs.new_run("M08", a.name, step="S2", owner="Aditya", command=command, seed=a.seed, quick=a.quick,
                           root=Path.cwd(), runs_dir=a.out, backend=backend,
                           params={"targets": names, "n_per_class": n_per_class, "calibration_per_class": CAL_PER_CLASS,
                                   "chunk": CHUNK, "min_measurement_ms": MIN_MEASUREMENT_MS,
                                   "t_threshold": dudect.T_THRESHOLD, "percentile_crops": dudect.N_PERCENTILES,
                                   "log2n": LOG2N, "write_slots": WRITE_SLOTS, "leak_spins": LEAK_SPINS})
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    reason = None if backend.is_gpu else "numpy backend: no GPU on this machine"

    def save() -> list[dict[str, Any]]:
        metrics = metrics_of(results, a.quick, reason)
        body = {"metrics": metrics, "timer": "cupy.cuda.Event" if backend.is_gpu else None,
                "executed_by": "cupy.RawModule (nvrtc)" if backend.is_gpu else "numpy twins (vcloak.gpu.sim)",
                "t_threshold": dudect.T_THRESHOLD, "n_per_class": n_per_class, "quick": a.quick,
                "caveat": SHARED_GPU_CAVEAT, "errors": errors, "device": backend.device_info(),
                "targets": [{k: v for k, v in res.items() if k != "series"}
                            | ({"series": {n: {k: v for k, v in s.items() if k not in ("curve", "t_all")}
                                           for n, s in res["series"].items()}} if "series" in res else {})
                            for res in results]}
        (run_dir / "summary.json").write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
        return metrics

    with telemetry.Sampler(run_dir / "telemetry.csv", hz=TELEMETRY_HZ):
        for name in names:
            print(f"target {name}", flush=True)
            try:
                t = build_target(name, backend, a.seed, a.quick)
                res = (run_target(t, backend, n_per_class, a.seed, run_dir, log=lambda s: print(s, flush=True))
                       if backend.is_gpu else plumbing(t, a.seed))
                results.append(res)
            except Exception as e:  # noqa: BLE001 - one target must not lose the others; the error is recorded
                errors.append(f"{name}: {type(e).__name__}: {e}"[:500])
                print(f"  ERROR {errors[-1]}", flush=True)
            t = None  # type: ignore[assignment]  # release the device buffers of this target
            if backend.is_gpu:
                backend.xp.get_default_memory_pool().free_all_blocks()
            save()  # after every target: a runner that dies keeps what was measured
    metrics = save()

    bad = sum(res["mismatches"] for res in results)
    by_name = {res["target"]: res for res in results}
    unexpected = [n for n in CONTROLS if n in by_name and backend.is_gpu
                  and by_name[n]["verdict"] != by_name[n]["expected_verdict"]]
    fails = [n for n in (*TARGETS, *DIAG) if n in by_name and backend.is_gpu
             and any(s["verdict"] == dudect.FAIL for s in by_name[n]["series"].values())]
    notes = []
    if errors or bad or unexpected:
        status = "FAIL"
        if errors:
            notes.append(f"{len(errors)} target(s) raised: " + "; ".join(errors))
        if bad:
            notes.append(f"{bad} output elements differ from the reference")
        if unexpected:
            notes.append("control(s) with the wrong verdict (the harness is not trustworthy): " + ", ".join(unexpected))
    elif not backend.is_gpu:
        status = "NOT_MEASURED"
        notes.append("numpy backend: plumbing and output checks only, no timing measured")
    else:
        status = "OK"
    if fails:
        notes.append("dudect FAIL (timing depends on the class) for: " + ", ".join(fails))
    runs.finish_run(run_dir, status=status, notes="; ".join(notes))
    print(f"run dir     {run_dir}")
    print(f"backend     {backend.name}   N per class {n_per_class}   quick {a.quick}")
    for res in results:
        if "series" in res:
            for sname, s in res["series"].items():
                print(f"  {res['target']:<15} {sname:<10} max|t| {s['max_abs_t']:>10.3f}  {s['verdict']}"
                      f"  (expected {res['expected_verdict']})  r={res['r']}")
        else:
            print(f"  {res['target']:<15} {res['verdict']}  mismatches {res['mismatches']}")
    print(f"metrics     {len(metrics)}")
    print(f"status      {status}" + (f"   dudect FAIL: {', '.join(fails)}" if fails else ""))
    return 1 if status == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
