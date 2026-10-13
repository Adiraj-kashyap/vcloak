#!/usr/bin/env python3
"""Step 7 of SETUP.txt: is this machine ready to run a V-cloak job?   python check_setup.py

Prints one line per check. Exit 0: ready for both jobs. Exit 2: ready for the probe (job 1) only, the GPU
performance counters are missing or refused (job 2 would record NOT_MEASURED). Exit 1: not ready.
Nothing printed here is a result of the project: results exist only in a results zip that was ingested.
"""
from __future__ import annotations

import os
import shutil
import sys

import kit_common as kc

ADD = r"""
import cupy as cp
k = cp.RawKernel(r'''extern "C" __global__ void add(const int* a, const int* b, int* c, int n) {
    int i = blockIdx.x * blockDim.x + threadIdx.x; if (i < n) c[i] = a[i] + b[i]; }''', "add")
a = cp.arange(4096, dtype=cp.int32); b = cp.full(4096, 7, dtype=cp.int32); c = cp.zeros(4096, dtype=cp.int32)
k((16,), (256,), (a, b, c, cp.int32(4096)))
assert bool((c == a + b).all()), "the kernel ran but the sums are wrong"
print(cp.__version__, cp.cuda.runtime.runtimeGetVersion())
"""


def main() -> int:
    bad, counters = 0, True

    def line(ok: bool | None, what: str, detail: str) -> None:
        print(f"[{'OK  ' if ok else 'WARN' if ok is None else 'FAIL'}] {what:<22} {detail}")

    v = sys.version_info
    line(True if (3, 10) <= v[:2] <= (3, 12) else None, "python",
         f"{v.major}.{v.minor}.{v.micro}" + ("" if (3, 10) <= v[:2] <= (3, 12) else
                                            "  (SETUP.txt names 3.12; continue only if CuPy below is OK)"))
    try:
        line(True, "gpu", kc.gpu_name())
        line(True, "runner name", kc.runner_name() + "   (written into every result of this machine)")
    except kc.KitError as e:
        line(False, "gpu / runner name", str(e))
        return 1

    os.environ["PATH"] = kc.path_with_tools()
    rc, out = kc.run([sys.executable, "-c", ADD], timeout=600)
    if rc == 0:
        line(True, "cupy + kernel compile", "CuPy {}, CUDA runtime {}; a RawKernel compiled and added correctly"
             .format(*out.split()[-2:]))
    else:
        bad += 1
        line(False, "cupy + kernel compile", "SETUP.txt steps 3 and 5.\n" + out.strip()[-600:])
    for mod, pip in (("numpy", "numpy"), ("scipy", "scipy"), ("pynvml", "nvidia-ml-py"),
                     ("cryptography", "cryptography"), ("pytest", "pytest")):
        rc, out = kc.run([sys.executable, "-c", f"import {mod}"], timeout=120)
        if rc != 0:
            bad += 1
            line(False, f"import {mod}", f"python -m pip install {pip}")

    ncu = shutil.which("ncu")
    if ncu is None:
        counters = False
        line(None, "ncu", "not found: install the CUDA Toolkit (SETUP.txt step 3). Job 1 does not need it.")
    else:
        _, ver = kc.run([ncu, "--version"])
        line(True, "ncu", " ".join(ver.split())[:90])
        rc, out = kc.run([ncu, "--query-metrics"], timeout=600)
        if any(e in out for e in kc.PERM_ERRORS):
            counters = False
            line(None, "gpu counters", "REFUSED (ERR_NVGPUCTRPERM): SETUP.txt step 6, then run this again")
        elif rc != 0:
            counters = False
            line(None, "gpu counters", f"ncu --query-metrics ended with exit {rc}:\n" + out.strip()[-400:])
        else:
            line(True, "gpu counters", "ncu listed its metrics without a permission error "
                                       "(the proof is the VERDICT of job 2)")
    if bad:
        print("\nNOT READY: fix the FAIL lines.")
        return 1
    if not counters:
        print("\nREADY FOR JOB 1 ONLY. Job 2 (ncu) would record NOT_MEASURED: fix the counters first.")
        return 2
    print("\nREADY. Continue with RUN.txt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
