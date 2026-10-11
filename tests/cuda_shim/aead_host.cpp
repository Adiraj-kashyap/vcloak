// Runs kernels/poly1305.cu, kernels/aead_open.cu and kernels/aead_seal.cu on the CPU through cuda_shim.h.
//   aead_host poly <in> <out> <nbytes> <n> <grid> <block>          in: keys u32[8n], msgs u8[nbytes * n]
//   aead_host tag  <in> <out> <aad_nbytes> <box_nbytes> <n> <grid> <block>
//                                              in: key u32[8], nonces u32[3n], aad u8[..], boxes u8[box_nbytes * n]
//   aead_host seal <in> <out> <n> <grid> <block>      in: key u32[8], conv u64[n], seq u64[n], nonces u32[3n]
//   aead_host open <in> <out> <n> <q_conv> <grid> <block>          in: key u32[8], blobs u32[11n]
// out: the kernel's output arrays, concatenated in argument order. The keys are TEST keys.
#include "cuda_shim.h"

#include "aead_open.cu"
#include "aead_seal.cu"
#include "poly1305.cu"

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

static u32 arg32(const char* s)
{
    return (u32)strtoul(s, NULL, 10);
}

int main(int argc, char** argv)
{
    if (argc < 7) {
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
    if (!strcmp(mode, "poly") && na == 4) {
        u32 nbytes = arg32(a[0]), n = arg32(a[1]);
        std::vector<u32> keys((size_t)8 * n), tags((size_t)4 * n);
        std::vector<u8> msgs((size_t)nbytes * n + 1);  // + 1: data() of an empty vector may be null
        if (!read_all(in, keys.data(), 4, keys.size()) || !read_all(in, msgs.data(), 1, (size_t)nbytes * n)) {
            return 4;
        }
        shim_launch(arg32(a[2]), arg32(a[3]), [&] { poly1305_mac(keys.data(), msgs.data(), tags.data(), nbytes, n); });
        ok = write_all(out, tags.data(), 4, tags.size());
    } else if (!strcmp(mode, "tag") && na == 5) {
        u32 aad_nbytes = arg32(a[0]), box_nbytes = arg32(a[1]), n = arg32(a[2]);
        std::vector<u32> nonces((size_t)3 * n), tags((size_t)4 * n);
        std::vector<u8> aad((size_t)aad_nbytes + 1), boxes((size_t)box_nbytes * n + 1);
        if (!read_all(in, key, 4, 8) || !read_all(in, nonces.data(), 4, nonces.size())
            || !read_all(in, aad.data(), 1, aad_nbytes) || !read_all(in, boxes.data(), 1, (size_t)box_nbytes * n)) {
            return 4;
        }
        shim_launch(arg32(a[3]), arg32(a[4]), [&] {
            aead_tag(key, nonces.data(), aad.data(), boxes.data(), tags.data(), aad_nbytes, box_nbytes, n);
        });
        ok = write_all(out, tags.data(), 4, tags.size());
    } else if (!strcmp(mode, "seal") && na == 3) {
        u32 n = arg32(a[0]);
        std::vector<u64> conv(n), seq(n);
        std::vector<u32> nonces((size_t)3 * n), blobs((size_t)SEQ_WORDS * n);
        if (!read_all(in, key, 4, 8) || !read_all(in, conv.data(), 8, n) || !read_all(in, seq.data(), 8, n)
            || !read_all(in, nonces.data(), 4, nonces.size())) {
            return 4;
        }
        shim_launch(arg32(a[1]), arg32(a[2]),
                    [&] { aead_seal_seq(key, conv.data(), seq.data(), nonces.data(), blobs.data(), n); });
        ok = write_all(out, blobs.data(), 4, blobs.size());
    } else if (!strcmp(mode, "open") && na == 4) {
        u32 n = arg32(a[0]);
        u64 q_conv = strtoull(a[1], NULL, 10);
        std::vector<u32> blobs((size_t)SEQ_WORDS * n), okc(n);
        std::vector<u64> hi(n), lo(n);
        if (!read_all(in, key, 4, 8) || !read_all(in, blobs.data(), 4, blobs.size())) {
            return 4;
        }
        shim_launch(arg32(a[2]), arg32(a[3]),
                    [&] { aead_open_seq(key, blobs.data(), n, q_conv, hi.data(), lo.data(), okc.data()); });
        ok = write_all(out, hi.data(), 8, n) && write_all(out, lo.data(), 8, n) && write_all(out, okc.data(), 4, n);
    } else {
        return 5;
    }
    fclose(in);
    return (fclose(out) == 0 && ok) ? 0 : 6;
}
