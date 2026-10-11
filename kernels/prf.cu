// ChaCha20 block function as a PRF: subkey derivation and the bucket PRF (ai/ARCHITECTURE.md §5).
// Keys are read through device pointers and never passed by value (ADR-003). Every branch and array
// index is built from thread/block ids and the public parameters n and B (ai/CONVENTIONS.md §2;
// checked by scripts/check_oblivious.py). NumPy twins: vcloak.gpu.sim. Host wrappers: vcloak.gpu.kernels.
#include "chacha20.cuh"

#define N_SUBKEYS 3

// K_x = ChaCha20Block(K_master, counter = 0, nonce = label_x)[0:32]. Thread t derives subkey t
// (0 tag, 1 seq, 2 bkt) into out_keys[8t .. 8t + 7], which is that key's word layout for chacha_block.
extern "C" __global__
void derive_subkeys(const u32* master, u32* out_keys)
{
    // "vcloak-tag\0\0", "vcloak-seq\0\0", "vcloak-bkt\0\0" as little-endian words
    const u32 LABELS[3 * N_SUBKEYS] = {0x6f6c6376u, 0x742d6b61u, 0x00006761u,
                                       0x6f6c6376u, 0x732d6b61u, 0x00007165u,
                                       0x6f6c6376u, 0x622d6b61u, 0x0000746bu};
    u32 t = blockIdx.x * blockDim.x + threadIdx.x;
    if (t >= N_SUBKEYS) {
        return;
    }
    u32 nonce[3];
    for (u32 w = 0; w < 3; ++w) {
        nonce[w] = LABELS[3 * t + w];
    }
    u32 ks[16];
    chacha_block(master, 0, nonce, ks);
    for (u32 w = 0; w < 8; ++w) {
        out_keys[8 * t + w] = ks[w];
    }
}

// bucket = LE32(ChaCha20Block(K_bkt, counter = 0, nonce = LE64(conv_id) || 00000000)[0:4]) mod B.
// One thread per conversation id; B >= 1 is public.
extern "C" __global__
void bucket_prf(const u32* kbkt, const u64* conv_ids, u32* out_bucket, u32 n, u32 B)
{
    u32 t = blockIdx.x * blockDim.x + threadIdx.x;
    if (t >= n) {
        return;
    }
    u64 conv = conv_ids[t];
    u32 nonce[3];
    nonce[0] = (u32)conv;
    nonce[1] = (u32)(conv >> 32);
    nonce[2] = 0;
    u32 ks[16];
    chacha_block(kbkt, 0, nonce, ks);
    out_bucket[t] = mod_public(ks[0], B);
}
