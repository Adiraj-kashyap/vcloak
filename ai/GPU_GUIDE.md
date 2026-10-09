# GPU GUIDE — CUDA via CuPy, and measurement methodology

## 1. Toolchain (decided in M00, recorded in STATE.env)
- NVIDIA driver + **CUDA Toolkit 12.x** (provides NVRTC for CuPy, and `nvcc`, `cuobjdump`, `ncu`).
- `pip install cupy-cuda12x nvidia-ml-py`. If the driver only supports CUDA 11.x, use `cupy-cuda11x`
  and record it.
- Windows: native Windows or WSL2 both work. Record which one. `ncu` counters on Windows need
  "Allow access to the GPU performance counters to all users" (NVIDIA Control Panel → Developer),
  or an administrator shell. On Linux they need `NVreg_RestrictProfilingToAdminUsers=0` or sudo.

## 2. Loading kernels
```python
src = Path("kernels/bitonic.cu").read_text()
mod = cp.RawModule(code=src, options=("-std=c++17", "-I" + str(KERNEL_DIR)),
                   name_expressions=("bitonic_pairs_global", "bitonic_shared"))
fn = mod.get_function("bitonic_pairs_global")
fn((grid,), (block,), (d_hi, d_lo, d_slot, d_pay, np.uint32(k), np.uint32(j), np.uint32(n)))
```
- All kernels are `extern "C" __global__` (or use `name_expressions`). Shared headers live in `kernels/*.cuh`.
- The same `.cu` files must also compile with `nvcc -cubin -arch=sm_<cc> -std=c++17` for SASS checks (M08).

## 3. Kernel patterns
**Bitonic, global stage (j ≥ block span):** launch n/2 threads; thread t handles exactly one pair:
```
i = (t / j) * 2 * j + (t % j);   l = i + j;   asc = ((i & k) == 0);
gt = lexicographic (hi, lo, slot)[i] > [l]   -> as a 64-bit mask
sw = ~(asc_mask ^ gt_mask)  (swap when order is wrong)   -> xor-swap all columns with sw
```
**Bitonic, shared stage:** each block loads 2*T consecutive elements (T threads) into shared memory
and runs every remaining (k, j) stage with j ≤ T, with `__syncthreads()` between stages. When
k ≤ 2T, the entire sort for that tile happens in one launch. Stage loops depend only on public k, j, T.

**ChaCha20:** one thread per 64-byte block; the 20-round core on 32-bit words with rotates;
counter = global block index; write 64 bytes (= 4 tags). Validate against RFC 8439 §2.3.2 test vectors.

**Poly1305:** 26-bit limbs (poly1305-donna style), 32×32→64 multiplies, carries by shifts and
masks; the final reduction selects by mask. Tag verification is constant-time.

**Columns (SoA):** `uint64 hi[n], lo[n]; uint32 slot[n], pay[n]`. 24 bytes per element.

## 4. Timing methodology (all GPU numbers)
```python
start, end = cp.cuda.Event(), cp.cuda.Event()
for _ in range(WARMUP): run()
cp.cuda.Stream.null.synchronize()
times = []
for _ in range(RUNS):
    start.record(); run(); end.record(); end.synchronize()
    times.append(cp.cuda.get_elapsed_time(start, end))   # ms
```
- WARMUP ≥ 10, RUNS ≥ 30 (default 50; quick mode 15). Report median, p5, p95, mean, std, CV.
- Separate H2D, kernels and D2H with events on the same stream for pipeline stage breakdowns.
- Use pinned host memory (`cp.cuda.alloc_pinned_memory`) for transfers in pipeline benchmarks.
- Time sweeps over n in powers of two from 2^10 up to `STATE.env.max_log2n`.

## 5. Derived metrics
- keys/s = n / median_time.
- Bitonic bytes moved ≈ rounds × n × 24 B × 2 (read + write); effective BW = bytes / time;
  % of peak = effective / theoretical peak (peak = 2 × mem_clock × bus_width / 8, from NVML/device attributes).
- rounds(n) = log2(n)·(log2(n)+1)/2; compare-exchanges = rounds · n/2.
- Crossover n*: the smallest n where the GPU median (kernels + transfers) < the best CPU oblivious baseline.

## 6. Telemetry (`vcloak.gpu.telemetry`, NVML via `pynvml`)
Snapshot fields: gpu name, driver, SM clock, mem clock, temperature, power draw, power limit,
utilisation (gpu, mem), clocks-throttle-reasons bitmask, pstate. Sample at 10 Hz in a background
thread during long runs; save to `telemetry.csv` in the run dir. If `nvidia-smi -lgc` (clock lock)
is permitted, record the locked clock; otherwise record `clocks: unlocked`.

## 7. Side-channel measurements (M08)
- **dudect (timing):** two input classes (A: fixed input, e.g. all-equal tags or sorted; B: fresh random).
  Interleave classes randomly. Measure each launch with CUDA events (batch several launches if a
  single one is under 50 µs). Welch t-test on the measurement sets, also on dudect's percentile
  crops. PASS if |t| < 4.5 at N ≥ 10^5 per class (quick: 10^4, reported as quick).
  Targets: bitonic (n=2^16), full write_epoch, and AEAD-open with valid vs invalid tags.
- **Divergence (ncu):** first run `ncu --query-metrics | grep -i branch` to confirm metric names on
  this version. Collect branch efficiency / divergent-branch metrics for the comparator kernels.
  Expected: 100% branch efficiency, 0 divergent branches.
- **SASS:** `nvcc -cubin -arch=sm_<cc>` then `cuobjdump -sass`. Save the listing. Every `BRA`/predicated
  branch must be traceable to loop counters or ids (explain each one in the audit notes).

## 8. VRAM budget
max_log2n = floor(log2(0.5 × free_VRAM / 48 B)) (double buffering), capped at 24. Record it in STATE.env.
Keys occupy under 1 KB; zeroize them on shutdown with `cp.cuda.runtime.memset`.
