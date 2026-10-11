// Shared mask helpers for the oblivious kernels (ai/CONVENTIONS.md §2).
// Nothing here branches on, or indexes memory by, a data value: comparisons are turned into 64-bit
// masks and every swap is an unconditional xor-swap under that mask.
// NumPy twins: vcloak.gpu.sim (_mask64, _lex_gt3, _cmp_exchange).
#pragma once

typedef unsigned long long u64;
typedef unsigned int u32;

// All ones when c is non-zero, else zero.
__device__ __forceinline__ u64 mask64(u64 c)
{
    return (u64)0 - (u64)(c != 0);
}

// Mask of (hi_a, lo_a, slot_a) > (hi_b, lo_b, slot_b) in lexicographic order. Uses &, | and comparisons
// only: no short-circuit operator, so every limb is always compared.
__device__ __forceinline__ u64 lex_gt3(u64 hi_a, u64 lo_a, u32 slot_a, u64 hi_b, u64 lo_b, u32 slot_b)
{
    u64 gt_hi = (u64)(hi_a > hi_b);
    u64 eq_hi = (u64)(hi_a == hi_b);
    u64 gt_lo = (u64)(lo_a > lo_b);
    u64 eq_lo = (u64)(lo_a == lo_b);
    u64 gt_slot = (u64)(slot_a > slot_b);
    return mask64(gt_hi | (eq_hi & (gt_lo | (eq_lo & gt_slot))));
}

// Swap a and b when m is all ones; leave them when m is zero. Both are always written.
__device__ __forceinline__ void xor_swap64(u64& a, u64& b, u64 m)
{
    u64 d = (a ^ b) & m;
    a ^= d;
    b ^= d;
}

__device__ __forceinline__ void xor_swap32(u32& a, u32& b, u64 m)
{
    u32 d = (a ^ b) & (u32)m;
    a ^= d;
    b ^= d;
}

// w mod B for a public modulus B >= 1, without dividing by data. Barrett reduction with the public
// constant m = floor((2^64 - 1) / B): q = floor(w * m / 2^64) is floor(w / B) or one less, so
// r = w - q * B lies in [0, 2B) and one masked subtraction finishes. The only division has public
// operands. w < 2^32, so the high half of w * m is built from two 32 x 32 -> 64 products.
__device__ __forceinline__ u32 mod_public(u32 w, u32 B)
{
    u64 m = 0xFFFFFFFFFFFFFFFFull / (u64)B;
    u64 m_hi = m >> 32;
    u64 m_lo = m & 0xFFFFFFFFull;
    u64 q = ((u64)w * m_hi + (((u64)w * m_lo) >> 32)) >> 32;
    u64 r = (u64)w - q * (u64)B;
    r -= (u64)B & mask64((u64)(r >= (u64)B));
    return (u32)r;
}

// One compare-exchange on the pair (i, l) of the SoA record (hi, lo, slot, pay). `asc` is the public
// direction mask of the pair. The payload moves under the same mask as its key columns. The caller
// guarantees that no other thread touches elements i and l in this launch or stage (ADR-005).
__device__ __forceinline__ void cmp_exchange(u64* hi, u64* lo, u32* slot, u32* pay, u32 i, u32 l, u64 asc)
{
    u64 a_hi = hi[i];
    u64 b_hi = hi[l];
    u64 a_lo = lo[i];
    u64 b_lo = lo[l];
    u32 a_slot = slot[i];
    u32 b_slot = slot[l];
    u32 a_pay = pay[i];
    u32 b_pay = pay[l];
    u64 gt = lex_gt3(a_hi, a_lo, a_slot, b_hi, b_lo, b_slot);
    u64 sw = ~(asc ^ gt);  // swap when the pair is in the wrong order for its direction
    xor_swap64(a_hi, b_hi, sw);
    xor_swap64(a_lo, b_lo, sw);
    xor_swap32(a_slot, b_slot, sw);
    xor_swap32(a_pay, b_pay, sw);
    hi[i] = a_hi;
    hi[l] = b_hi;
    lo[i] = a_lo;
    lo[l] = b_lo;
    slot[i] = a_slot;
    slot[l] = b_slot;
    pay[i] = a_pay;
    pay[l] = b_pay;
}
