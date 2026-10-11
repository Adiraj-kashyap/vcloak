// Runs kernels/chacha_tags.cu and kernels/prf.cu on the CPU through cuda_shim.h.
//   chacha_host blocks  <in> <out> <counter0> <nblocks> <grid> <block>    in: key u32[8], nonce u32[3]
//   chacha_host tags    <in> <out> <nonce_lo> <nonce_hi> <nblocks> <grid> <block>    in: key u32[8]
//   chacha_host subkeys <in> <out> <grid> <block>                         in: master u32[8]
//   chacha_host bucket  <in> <out> <n> <B> <grid> <block>                 in: key u32[8], conv_ids u64[n]
//   chacha_host mod     <in> <out> <n> <B>                                in: w u32[n]  (mod_public alone)
// out: the kernel's output arrays, concatenated in argument order. The keys are TEST keys.
#include "cuda_shim.h"

#include "chacha_tags.cu"
#include "prf.cu"

#include <cstdio>
#include <cstdlib>
#include <cstring>

static bool read_all(FILE* f, void* p, size_t size, size_t count)
{
    return count == 0 || fread(p, size, count, f) == count;
}

static bool write_all(FILE* f, const void* p, size_t size, size_t count)
{
    return count == 0 || fwrite(p, size, count, f) == count;
}

int main(int argc, char** argv)
{
    if (argc < 6) {
        return 2;
    }
    const char* mode = argv[1];
    FILE* in = fopen(argv[2], "rb");
    FILE* out = fopen(argv[3], "wb");
    if (!in || !out) {
        return 3;
    }
    char** a = argv + 4;
    int na = argc - 4;
    bool ok = false;
    u32 key[8];
    if (!strcmp(mode, "blocks") && na == 4) {
        u32 nonce[3];
        u32 counter0 = (u32)strtoul(a[0], NULL, 10), nblocks = (u32)strtoul(a[1], NULL, 10);
        std::vector<u32> ks((size_t)16 * nblocks);
        if (!read_all(in, key, 4, 8) || !read_all(in, nonce, 4, 3)) {
            return 4;
        }
        shim_launch((u32)strtoul(a[2], NULL, 10), (u32)strtoul(a[3], NULL, 10),
                    [&] { chacha_blocks(key, nonce, ks.data(), counter0, nblocks); });
        ok = write_all(out, ks.data(), 4, ks.size());
    } else if (!strcmp(mode, "tags") && na == 5) {
        u64 nonce_lo = strtoull(a[0], NULL, 10);
        u32 nonce_hi = (u32)strtoul(a[1], NULL, 10), nblocks = (u32)strtoul(a[2], NULL, 10);
        std::vector<u64> hi((size_t)4 * nblocks), lo((size_t)4 * nblocks);
        if (!read_all(in, key, 4, 8)) {
            return 4;
        }
        shim_launch((u32)strtoul(a[3], NULL, 10), (u32)strtoul(a[4], NULL, 10),
                    [&] { chacha_tags(key, nonce_lo, nonce_hi, hi.data(), lo.data(), nblocks); });
        ok = write_all(out, hi.data(), 8, hi.size()) && write_all(out, lo.data(), 8, lo.size());
    } else if (!strcmp(mode, "subkeys") && na == 2) {
        u32 keys[3 * 8];
        if (!read_all(in, key, 4, 8)) {
            return 4;
        }
        shim_launch((u32)strtoul(a[0], NULL, 10), (u32)strtoul(a[1], NULL, 10), [&] { derive_subkeys(key, keys); });
        ok = write_all(out, keys, 4, 3 * 8);
    } else if (!strcmp(mode, "bucket") && na == 4) {
        u32 n = (u32)strtoul(a[0], NULL, 10), B = (u32)strtoul(a[1], NULL, 10);
        std::vector<u64> conv(n);
        std::vector<u32> bucket(n);
        if (!read_all(in, key, 4, 8) || !read_all(in, conv.data(), 8, n)) {
            return 4;
        }
        shim_launch((u32)strtoul(a[2], NULL, 10), (u32)strtoul(a[3], NULL, 10),
                    [&] { bucket_prf(key, conv.data(), bucket.data(), n, B); });
        ok = write_all(out, bucket.data(), 4, n);
    } else if (!strcmp(mode, "mod") && na == 2) {
        u32 n = (u32)strtoul(a[0], NULL, 10), B = (u32)strtoul(a[1], NULL, 10);
        std::vector<u32> w(n);
        if (!read_all(in, w.data(), 4, n)) {
            return 4;
        }
        for (u32 i = 0; i < n; ++i) {
            w[i] = mod_public(w[i], B);
        }
        ok = write_all(out, w.data(), 4, n);
    } else {
        return 5;
    }
    fclose(in);
    return (fclose(out) == 0 && ok) ? 0 : 6;
}
