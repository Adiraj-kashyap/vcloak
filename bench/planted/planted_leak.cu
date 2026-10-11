// M08 S1: a kernel that LEAKS ON PURPOSE. It is the positive control of the dudect harness
// (bench/run_dudect.py): if the harness cannot see this, a PASS on the real kernels means nothing.
// It lives outside kernels/ because it breaks ai/CONVENTIONS.md §2.1 by design, and
// scripts/check_oblivious.py must flag it (tests/unit/test_dudect_harness.py). Never used by the service.
// NumPy twin: vcloak.gpu.sim.planted_leak.
typedef unsigned int u32;

// out[t] = x[t] when x[t] == 0, else x[t] advanced `spins` steps of a 32-bit LCG.
extern "C" __global__
void planted_leak(const u32* x, u32* out, u32 n, u32 spins)
{
    u32 t = blockIdx.x * blockDim.x + threadIdx.x;
    if (t >= n) {
        return;
    }
    u32 acc = x[t];
    if (x[t]) {  // the planted leak: a branch on the data, and work that only one side does
        for (u32 s = 0; s < spins; ++s) {
            acc = acc * 1664525u + 1013904223u;
        }
    }
    out[t] = acc;
}
