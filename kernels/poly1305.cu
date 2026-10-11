// General-length Poly1305 and AEAD-tag kernels: one thread per message, all messages of one launch
// having the same public byte count. They exist so that the device code of poly1305.cuh is checked
// against RFC 8439 §2.5.2 and §2.8.2 and against the reference at every block alignment; the service
// uses the fixed-size kernels of aead_open.cu and aead_seal.cu. Every branch and array index is built
// from thread/block ids and the public parameters n, nbytes, aad_nbytes and box_nbytes
// (ai/CONVENTIONS.md §2; checked by scripts/check_oblivious.py).
// NumPy twins: vcloak.gpu.sim. Host wrappers: vcloak.gpu.kernels.
#include "chacha20.cuh"
#include "poly1305.cuh"

// Thread t: tag of msgs[nbytes * t .. nbytes * (t + 1)) under the one-time key keys[8t .. 8t + 7].
extern "C" __global__
void poly1305_mac(const u32* keys, const u8* msgs, u32* out_tags, u32 nbytes, u32 n)
{
    u32 t = blockIdx.x * blockDim.x + threadIdx.x;
    if (t >= n) {
        return;
    }
    u32 r[5];
    u32 h[5];
    u32 tag[4];
    poly1305_init(keys + 8 * (u64)t, r, h);
    poly1305_bytes(r, h, msgs + (u64)nbytes * t, nbytes, 1u, 0u);
    poly1305_finish(keys + 8 * (u64)t, h, tag);
    for (u32 w = 0; w < 4; ++w) {
        out_tags[4 * t + w] = tag[w];
    }
}

// RFC 8439 §2.8 tag of ciphertext t under (key, nonce t) with one shared aad:
// Poly1305(otk, aad || pad16 || ciphertext || pad16 || LE64(aad_nbytes) || LE64(box_nbytes)),
// otk = ChaCha20 block 0. The ciphertext itself is the keystream from block 1 (chacha_blocks).
extern "C" __global__
void aead_tag(const u32* key, const u32* nonces, const u8* aad, const u8* boxes, u32* out_tags, u32 aad_nbytes,
              u32 box_nbytes, u32 n)
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
    chacha_block(key, 0, nonce, otk);
    u32 r[5];
    u32 h[5];
    u32 tag[4];
    u32 lens[4];
    lens[0] = aad_nbytes;
    lens[1] = 0;
    lens[2] = box_nbytes;
    lens[3] = 0;
    poly1305_init(otk, r, h);
    poly1305_bytes(r, h, aad, aad_nbytes, 0u, POLY_HIBIT);
    poly1305_bytes(r, h, boxes + (u64)box_nbytes * t, box_nbytes, 0u, POLY_HIBIT);
    poly1305_block(r, h, lens, POLY_HIBIT);
    poly1305_finish(otk, h, tag);
    for (u32 w = 0; w < 4; ++w) {
        out_tags[4 * t + w] = tag[w];
    }
}
