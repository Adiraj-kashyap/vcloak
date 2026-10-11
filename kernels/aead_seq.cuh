// The fixed-size seq_enc AEAD (ai/ARCHITECTURE.md §5), shared by aead_open.cu and aead_seal.cu:
//   seq_enc (44 B) = nonce(12) || ChaCha20-Poly1305(K_seq, nonce, pt = LE64(conv_id) || LE64(seq),
//                                                    aad = "vcloak-seq-v1")
// As 11 little-endian words per row: nonce 0..2, ciphertext 3..6, tag 7..10. The MAC input of
// RFC 8439 §2.8 is exactly three 16-byte blocks here: aad || 000000, ciphertext, LE64(13) || LE64(16).
// NumPy twin: vcloak.gpu.sim._seq_tag.
#pragma once
#include "chacha20.cuh"
#include "poly1305.cuh"

#define SEQ_WORDS 11
#define SEQ_CT 3   // first ciphertext word of a row
#define SEQ_TAG 7  // first tag word of a row

// Tag of one row. `otk` is ChaCha20 block 0 under (K_seq, nonce): words 0..7 are the one-time key.
__device__ __forceinline__ void seq_tag(const u32* otk, const u32* ct, u32* tag)
{
    const u32 AAD[4] = {0x6f6c6376u, 0x732d6b61u, 0x762d7165u, 0x00000031u};  // "vcloak-seq-v1" 00 00 00
    const u32 LENS[4] = {13u, 0u, 16u, 0u};                                    // LE64(13) || LE64(16)
    u32 r[5];
    u32 h[5];
    poly1305_init(otk, r, h);
    poly1305_block(r, h, AAD, POLY_HIBIT);
    poly1305_block(r, h, ct, POLY_HIBIT);
    poly1305_block(r, h, LENS, POLY_HIBIT);
    poly1305_finish(otk, h, tag);
}
