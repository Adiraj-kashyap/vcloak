// ChaCha20 block function (RFC 8439 §2.3), the only server-side primitive besides Poly1305 (ADR-003).
// Add, xor and rotate by a constant on 32-bit words: no table, no branch and no index that depends on
// the key, the nonce or the state. The loop bounds and subscripts below are literals and loop counters.
// NumPy twin: vcloak.gpu.sim._chacha_block.
#pragma once
#include "common.cuh"

__device__ __forceinline__ u32 rotl32(u32 x, u32 r)
{
    return (x << r) | (x >> (32 - r));
}

__device__ __forceinline__ void chacha_qr(u32& a, u32& b, u32& c, u32& d)
{
    a += b;
    d = rotl32(d ^ a, 16);
    c += d;
    b = rotl32(b ^ c, 12);
    a += b;
    d = rotl32(d ^ a, 8);
    c += d;
    b = rotl32(b ^ c, 7);
}

// One 64-byte block as 16 little-endian words: state = sigma(4) || key(8) || ctr(1) || nonce(3),
// 20 rounds, then the feed-forward. `out` must not alias `key` or `nonce`.
__device__ __forceinline__ void chacha_block(const u32* key, u32 ctr, const u32* nonce, u32* out)
{
    u32 s[16];
    u32 x[16];
    s[0] = 0x61707865u;  // "expand 32-byte k"
    s[1] = 0x3320646eu;
    s[2] = 0x79622d32u;
    s[3] = 0x6b206574u;
    for (u32 w = 0; w < 8; ++w) {
        s[4 + w] = key[w];
    }
    s[12] = ctr;
    for (u32 w = 0; w < 3; ++w) {
        s[13 + w] = nonce[w];
    }
    for (u32 w = 0; w < 16; ++w) {
        x[w] = s[w];
    }
    for (u32 r = 0; r < 10; ++r) {
        chacha_qr(x[0], x[4], x[8], x[12]);
        chacha_qr(x[1], x[5], x[9], x[13]);
        chacha_qr(x[2], x[6], x[10], x[14]);
        chacha_qr(x[3], x[7], x[11], x[15]);
        chacha_qr(x[0], x[5], x[10], x[15]);
        chacha_qr(x[1], x[6], x[11], x[12]);
        chacha_qr(x[2], x[7], x[8], x[13]);
        chacha_qr(x[3], x[4], x[9], x[14]);
    }
    for (u32 w = 0; w < 16; ++w) {
        out[w] = x[w] + s[w];
    }
}
