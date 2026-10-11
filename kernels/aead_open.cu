// Read path R2: open seq_enc on the device and emit the restore-sort keys (ai/ARCHITECTURE.md §2, §5).
// One thread per candidate row. K_seq is read through a device pointer and never passed by value
// (ADR-003). The authentication result never steers a branch or an address: the tag is compared by
// OR-accumulating XOR differences, and a failed or foreign row becomes a sort key by masks
// (ai/CONVENTIONS.md §2.3, §2.5; checked by scripts/check_oblivious.py).
// NumPy twin: vcloak.gpu.sim.aead_open_seq. Host wrapper: vcloak.gpu.kernels.gpu_open_and_key.
#include "aead_seq.cuh"

// blobs: SEQ_WORDS words per row. q_conv: the conversation being read. For row t:
//   ok   = 1 when the tag verifies, else 0
//   miss = (1 - ok) | (conv != q_conv)        -> out_hi (0 hit, 1 miss)
//   out_lo = seq when it is a hit, 0 on a miss
// Sorting by (hi, lo, slot) then puts the conversation's rows first, in sequence order.
extern "C" __global__
void aead_open_seq(const u32* kseq, const u32* blobs, u32 n, u64 q_conv, u64* out_hi, u64* out_lo, u32* out_ok)
{
    u32 t = blockIdx.x * blockDim.x + threadIdx.x;
    if (t >= n) {
        return;
    }
    u32 nonce[3];
    for (u32 w = 0; w < 3; ++w) {
        nonce[w] = blobs[SEQ_WORDS * t + w];
    }
    u32 otk[16];
    u32 ks[16];
    chacha_block(kseq, 0, nonce, otk);  // block 0: the Poly1305 one-time key
    chacha_block(kseq, 1, nonce, ks);   // block 1: the keystream of the 16-byte plaintext
    u32 ct[4];
    u32 tag[4];
    for (u32 w = 0; w < 4; ++w) {
        ct[w] = blobs[SEQ_WORDS * t + SEQ_CT + w];
    }
    seq_tag(otk, ct, tag);
    u32 diff = 0;
    for (u32 w = 0; w < 4; ++w) {
        diff |= tag[w] ^ blobs[SEQ_WORDS * t + SEQ_TAG + w];
    }
    u64 ok = (u64)(diff == 0);
    u64 conv = (u64)(ct[0] ^ ks[0]) | ((u64)(ct[1] ^ ks[1]) << 32);
    u64 seq = (u64)(ct[2] ^ ks[2]) | ((u64)(ct[3] ^ ks[3]) << 32);
    u64 miss = ((u64)1 - ok) | (u64)(conv != q_conv);
    out_hi[t] = miss;
    out_lo[t] = seq & ~mask64(miss);
    out_ok[t] = (u32)ok;
}
