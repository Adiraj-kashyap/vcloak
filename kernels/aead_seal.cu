// Write path: seal seq_enc on the device (ai/ARCHITECTURE.md §5). One thread per row. K_seq is read
// through a device pointer and never passed by value (ADR-003). The nonces come from the host: they
// are public random data (ai/CONVENTIONS.md §3). Every branch and array index is built from
// thread/block ids and the public row count n (checked by scripts/check_oblivious.py).
// NumPy twin: vcloak.gpu.sim.aead_seal_seq. Host wrapper: vcloak.gpu.kernels.gpu_seal_seq.
#include "aead_seq.cuh"

// nonces: 3 words per row. out_blobs: SEQ_WORDS words per row = nonce || ciphertext || tag.
extern "C" __global__
void aead_seal_seq(const u32* kseq, const u64* conv_ids, const u64* seqs, const u32* nonces, u32* out_blobs, u32 n)
{
    u32 t = blockIdx.x * blockDim.x + threadIdx.x;
    if (t >= n) {
        return;
    }
    u32 nonce[3];
    for (u32 w = 0; w < 3; ++w) {
        nonce[w] = nonces[3 * t + w];
    }
    u32 otk[16];
    u32 ks[16];
    chacha_block(kseq, 0, nonce, otk);
    chacha_block(kseq, 1, nonce, ks);
    u64 conv = conv_ids[t];
    u64 seq = seqs[t];
    u32 ct[4];
    u32 tag[4];
    ct[0] = (u32)conv ^ ks[0];
    ct[1] = (u32)(conv >> 32) ^ ks[1];
    ct[2] = (u32)seq ^ ks[2];
    ct[3] = (u32)(seq >> 32) ^ ks[3];
    seq_tag(otk, ct, tag);
    for (u32 w = 0; w < 3; ++w) {
        out_blobs[SEQ_WORDS * t + w] = nonce[w];
    }
    for (u32 w = 0; w < 4; ++w) {
        out_blobs[SEQ_WORDS * t + SEQ_CT + w] = ct[w];
        out_blobs[SEQ_WORDS * t + SEQ_TAG + w] = tag[w];
    }
}
