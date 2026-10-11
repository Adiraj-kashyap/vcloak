// ChaCha20 keystream kernels: one thread per 64-byte block (ai/GPU_GUIDE.md §3).
// The key is read through a device pointer and never passed by value (ADR-003). Every branch and
// array index is built from thread/block ids and the public parameters nblocks and counter0
// (ai/CONVENTIONS.md §2; checked by scripts/check_oblivious.py).
// NumPy twins: vcloak.gpu.sim. Host wrappers: vcloak.gpu.kernels.
#include "chacha20.cuh"

// Raw blocks: thread t writes block counter0 + t as 16 little-endian words to out[16t .. 16t + 15].
extern "C" __global__
void chacha_blocks(const u32* key, const u32* nonce, u32* out, u32 counter0, u32 nblocks)
{
    u32 t = blockIdx.x * blockDim.x + threadIdx.x;
    if (t >= nblocks) {
        return;
    }
    u32 ks[16];
    chacha_block(key, counter0 + t, nonce, ks);
    for (u32 w = 0; w < 16; ++w) {
        out[16 * t + w] = ks[w];
    }
}

// Sorting tags (ai/ARCHITECTURE.md §5): keystream of nonce LE64(nonce_lo) || LE32(nonce_hi) from
// counter 0. Thread t owns block t, which is the tags of slots 4t .. 4t + 3:
// hi = LE64(ks[16i .. 16i + 7]), lo = LE64(ks[16i + 8 .. 16i + 15]). nonce_lo is the epoch or the
// window, nonce_hi the domain word (0 for epoch tags, 0x80000000 for re-shuffle tags).
extern "C" __global__
void chacha_tags(const u32* key, u64 nonce_lo, u32 nonce_hi, u64* out_hi, u64* out_lo, u32 nblocks)
{
    u32 t = blockIdx.x * blockDim.x + threadIdx.x;
    if (t >= nblocks) {
        return;
    }
    u32 nonce[3];
    nonce[0] = (u32)nonce_lo;
    nonce[1] = (u32)(nonce_lo >> 32);
    nonce[2] = nonce_hi;
    u32 ks[16];
    chacha_block(key, t, nonce, ks);
    for (u32 q = 0; q < 4; ++q) {
        out_hi[4 * t + q] = (u64)ks[4 * q] | ((u64)ks[4 * q + 1] << 32);
        out_lo[4 * t + q] = (u64)ks[4 * q + 2] | ((u64)ks[4 * q + 3] << 32);
    }
}
