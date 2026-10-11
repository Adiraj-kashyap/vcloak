// Bitonic sorting network over SoA records (hi, lo, slot, pay), ordered by (hi, lo, slot).
// One thread owns one compare-exchange pair (ADR-005), so no element is written by two threads in a
// launch or, inside the shared kernels, between two __syncthreads() barriers.
// Every branch, loop bound and array index below is built from thread/block ids and the public
// parameters k, j, j_start, n, npairs and T = blockDim.x (ai/CONVENTIONS.md §2; checked by
// scripts/check_oblivious.py). NumPy twins: vcloak.gpu.sim. Host driver: vcloak.gpu.kernels.
#include "common.cuh"

#define MAX_T 256  // largest block size of the shared kernels; a tile holds 2 * MAX_T records (12 KiB)

// Global stage (k, j): launch npairs = n / 2 threads. Thread t owns the pair (i, i + j) with
// i = (t / j) * 2j + (t % j), written with masks because j is a power of two.
extern "C" __global__
void bitonic_pairs_global(u64* hi, u64* lo, u32* slot, u32* pay, u32 k, u32 j, u32 npairs)
{
    u32 t = blockIdx.x * blockDim.x + threadIdx.x;
    if (t >= npairs) {
        return;
    }
    u32 i = t + (t & ~(j - 1));
    u32 l = i + j;
    u64 asc = mask64((u64)((i & k) == 0));
    cmp_exchange(hi, lo, slot, pay, i, l, asc);
}

// Shared stages of one k: block b loads the tile [b * 2T, (b + 1) * 2T) into shared memory, runs the
// stages j = j_start, j_start / 2, ..., 1 (j_start <= T) and writes the tile back.
extern "C" __global__
void bitonic_shared(u64* hi, u64* lo, u32* slot, u32* pay, u32 k, u32 j_start, u32 n)
{
    __shared__ u64 s_hi[2 * MAX_T];
    __shared__ u64 s_lo[2 * MAX_T];
    __shared__ u32 s_slot[2 * MAX_T];
    __shared__ u32 s_pay[2 * MAX_T];
    u32 T = blockDim.x;
    u32 t = threadIdx.x;
    u32 base = blockIdx.x * 2 * T;
    if (base >= n) {  // uniform over the block, so no thread waits at a barrier alone
        return;
    }
    s_hi[t] = hi[base + t];
    s_hi[t + T] = hi[base + t + T];
    s_lo[t] = lo[base + t];
    s_lo[t + T] = lo[base + t + T];
    s_slot[t] = slot[base + t];
    s_slot[t + T] = slot[base + t + T];
    s_pay[t] = pay[base + t];
    s_pay[t + T] = pay[base + t + T];
    __syncthreads();
    for (u32 j = j_start; j > 0; j >>= 1) {
        u32 i = t + (t & ~(j - 1));
        u32 l = i + j;
        u64 asc = mask64((u64)(((base + i) & k) == 0));
        cmp_exchange(s_hi, s_lo, s_slot, s_pay, i, l, asc);
        __syncthreads();
    }
    hi[base + t] = s_hi[t];
    hi[base + t + T] = s_hi[t + T];
    lo[base + t] = s_lo[t];
    lo[base + t + T] = s_lo[t + T];
    slot[base + t] = s_slot[t];
    slot[base + t + T] = s_slot[t + T];
    pay[base + t] = s_pay[t];
    pay[base + t + T] = s_pay[t + T];
}

// The initial local sort: every stage with k <= 2T for the block's tile, in one launch.
extern "C" __global__
void bitonic_shared_full(u64* hi, u64* lo, u32* slot, u32* pay, u32 n)
{
    __shared__ u64 s_hi[2 * MAX_T];
    __shared__ u64 s_lo[2 * MAX_T];
    __shared__ u32 s_slot[2 * MAX_T];
    __shared__ u32 s_pay[2 * MAX_T];
    u32 T = blockDim.x;
    u32 t = threadIdx.x;
    u32 base = blockIdx.x * 2 * T;
    if (base >= n) {
        return;
    }
    s_hi[t] = hi[base + t];
    s_hi[t + T] = hi[base + t + T];
    s_lo[t] = lo[base + t];
    s_lo[t + T] = lo[base + t + T];
    s_slot[t] = slot[base + t];
    s_slot[t + T] = slot[base + t + T];
    s_pay[t] = pay[base + t];
    s_pay[t + T] = pay[base + t + T];
    __syncthreads();
    for (u32 k = 2; k <= 2 * T; k <<= 1) {
        for (u32 j = k >> 1; j > 0; j >>= 1) {
            u32 i = t + (t & ~(j - 1));
            u32 l = i + j;
            u64 asc = mask64((u64)(((base + i) & k) == 0));
            cmp_exchange(s_hi, s_lo, s_slot, s_pay, i, l, asc);
            __syncthreads();
        }
    }
    hi[base + t] = s_hi[t];
    hi[base + t + T] = s_hi[t + T];
    lo[base + t] = s_lo[t];
    lo[base + t + T] = s_lo[t + T];
    slot[base + t] = s_slot[t];
    slot[base + t + T] = s_slot[t + T];
    pay[base + t] = s_pay[t];
    pay[base + t + T] = s_pay[t + T];
}
