// Poly1305 one-time authenticator (RFC 8439 §2.5) on five 26-bit limbs (ai/GPU_GUIDE.md §3).
// 32 x 32 -> 64 multiplies, carries by shifts and masks, final reduction selected by a mask: no table,
// no branch and no index that depends on the key, the message or the accumulator. The only branches
// and subscripts are built from the public byte count of a message (poly1305_bytes).
// NumPy twins: vcloak.gpu.sim (_poly_init, _poly_block, _poly_bytes, _poly_finish).
#pragma once
#include "common.cuh"

typedef unsigned char u8;

#define POLY_LIMB 0x3ffffffu
#define POLY_HIBIT 0x1000000u  // 2^128 as bit 24 of limb 4: the 0x01 byte appended to a full 16-byte block

// r = the low 16 key bytes (4 little-endian words), clamped (§2.5.1), as limbs. The accumulator h = 0.
__device__ __forceinline__ void poly1305_init(const u32* key, u32* r, u32* h)
{
    r[0] = key[0] & 0x3ffffffu;
    r[1] = ((key[0] >> 26) | (key[1] << 6)) & 0x3ffff03u;
    r[2] = ((key[1] >> 20) | (key[2] << 12)) & 0x3ffc0ffu;
    r[3] = ((key[2] >> 14) | (key[3] << 18)) & 0x3f03fffu;
    r[4] = (key[3] >> 8) & 0x00fffffu;
    for (u32 w = 0; w < 5; ++w) {
        h[w] = 0;
    }
}

// h = (h + block) * r mod 2^130 - 5, partially reduced (limbs below 2^26, h1 may carry one bit more).
// `msg` is the 16-byte block as 4 little-endian words; `hibit` is POLY_HIBIT for a full block and 0
// for a final short block that already holds its 0x01 byte.
__device__ __forceinline__ void poly1305_block(const u32* r, u32* h, const u32* msg, u32 hibit)
{
    u64 r0 = r[0];
    u64 r1 = r[1];
    u64 r2 = r[2];
    u64 r3 = r[3];
    u64 r4 = r[4];
    u64 s1 = r1 * 5;
    u64 s2 = r2 * 5;
    u64 s3 = r3 * 5;
    u64 s4 = r4 * 5;
    u64 h0 = h[0] + (msg[0] & POLY_LIMB);
    u64 h1 = h[1] + (((msg[0] >> 26) | (msg[1] << 6)) & POLY_LIMB);
    u64 h2 = h[2] + (((msg[1] >> 20) | (msg[2] << 12)) & POLY_LIMB);
    u64 h3 = h[3] + (((msg[2] >> 14) | (msg[3] << 18)) & POLY_LIMB);
    u64 h4 = h[4] + ((msg[3] >> 8) | hibit);
    u64 d0 = h0 * r0 + h1 * s4 + h2 * s3 + h3 * s2 + h4 * s1;
    u64 d1 = h0 * r1 + h1 * r0 + h2 * s4 + h3 * s3 + h4 * s2;
    u64 d2 = h0 * r2 + h1 * r1 + h2 * r0 + h3 * s4 + h4 * s3;
    u64 d3 = h0 * r3 + h1 * r2 + h2 * r1 + h3 * r0 + h4 * s4;
    u64 d4 = h0 * r4 + h1 * r3 + h2 * r2 + h3 * r1 + h4 * r0;
    d1 += d0 >> 26;
    d2 += d1 >> 26;
    d3 += d2 >> 26;
    d4 += d3 >> 26;
    u64 e0 = (d0 & POLY_LIMB) + (d4 >> 26) * 5;
    h[0] = (u32)(e0 & POLY_LIMB);
    h[1] = (u32)((d1 & POLY_LIMB) + (e0 >> 26));
    h[2] = (u32)(d2 & POLY_LIMB);
    h[3] = (u32)(d3 & POLY_LIMB);
    h[4] = (u32)(d4 & POLY_LIMB);
}

// Little-endian word at byte offset i of msg. i is public.
__device__ __forceinline__ u32 load_le32(const u8* msg, u32 i)
{
    return (u32)msg[i] | ((u32)msg[i + 1] << 8) | ((u32)msg[i + 2] << 16) | ((u32)msg[i + 3] << 24);
}

// Absorb nbytes bytes: every full 16-byte block, then the rest as one short block. The byte count is
// public, so the loop bounds and the buffer subscripts are public. A short block ends with pad_byte
// and is absorbed with pad_hibit: (1, 0) is plain Poly1305 (§2.5), (0, POLY_HIBIT) is the zero
// padding to a 16-byte boundary of the AEAD construction (§2.8).
__device__ __forceinline__ void poly1305_bytes(const u32* r, u32* h, const u8* msg, u32 nbytes, u32 pad_byte,
                                               u32 pad_hibit)
{
    u32 full = nbytes / 16;
    u32 rem = nbytes - 16 * full;
    u32 m[4];
    for (u32 b = 0; b < full; ++b) {
        for (u32 w = 0; w < 4; ++w) {
            m[w] = load_le32(msg, 16 * b + 4 * w);
        }
        poly1305_block(r, h, m, POLY_HIBIT);
    }
    if (rem > 0) {
        u8 buf[16];
        for (u32 b = 0; b < 16; ++b) {
            buf[b] = 0;
        }
        for (u32 b = 0; b < rem; ++b) {
            buf[b] = msg[16 * full + b];
        }
        buf[rem] = (u8)pad_byte;
        for (u32 w = 0; w < 4; ++w) {
            m[w] = load_le32(buf, 4 * w);
        }
        poly1305_block(r, h, m, pad_hibit);
    }
}

// tag = ((h mod 2^130 - 5) + s) mod 2^128 as 4 little-endian words; s = key bytes 16..31 (key[4..7]).
// h - p is computed alongside h and one of the two is kept by a mask (no branch on the comparison).
__device__ __forceinline__ void poly1305_finish(const u32* key, const u32* h, u32* tag)
{
    u32 h0 = h[0];
    u32 h1 = h[1];
    u32 h2 = h[2];
    u32 h3 = h[3];
    u32 h4 = h[4];
    u32 c = h1 >> 26;
    h1 &= POLY_LIMB;
    h2 += c;
    c = h2 >> 26;
    h2 &= POLY_LIMB;
    h3 += c;
    c = h3 >> 26;
    h3 &= POLY_LIMB;
    h4 += c;
    c = h4 >> 26;
    h4 &= POLY_LIMB;
    h0 += c * 5;
    c = h0 >> 26;
    h0 &= POLY_LIMB;
    h1 += c;
    u32 g0 = h0 + 5;
    c = g0 >> 26;
    g0 &= POLY_LIMB;
    u32 g1 = h1 + c;
    c = g1 >> 26;
    g1 &= POLY_LIMB;
    u32 g2 = h2 + c;
    c = g2 >> 26;
    g2 &= POLY_LIMB;
    u32 g3 = h3 + c;
    c = g3 >> 26;
    g3 &= POLY_LIMB;
    u32 g4 = h4 + c - (1u << 26);
    u32 sel = (g4 >> 31) - 1;  // all ones when h + 5 reached 2^130, i.e. h >= p: keep g = h - p
    h0 = (h0 & ~sel) | (g0 & sel);
    h1 = (h1 & ~sel) | (g1 & sel);
    h2 = (h2 & ~sel) | (g2 & sel);
    h3 = (h3 & ~sel) | (g3 & sel);
    h4 = (h4 & ~sel) | (g4 & sel);
    u64 f = (u64)(h0 | (h1 << 26)) + key[4];
    tag[0] = (u32)f;
    f = (u64)((h1 >> 6) | (h2 << 20)) + key[5] + (f >> 32);
    tag[1] = (u32)f;
    f = (u64)((h2 >> 12) | (h3 << 14)) + key[6] + (f >> 32);
    tag[2] = (u32)f;
    f = (u64)((h3 >> 18) | (h4 << 8)) + key[7] + (f >> 32);
    tag[3] = (u32)f;
}
