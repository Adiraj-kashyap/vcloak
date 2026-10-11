// Runs kernels/bitonic.cu on the CPU through cuda_shim.h.
//   bitonic_host <in.bin> <out.bin> <n> <plan.txt>
// in/out: the columns hi[n] u64, lo[n] u64, slot[n] u32, pay[n] u32, concatenated.
// plan.txt: one launch per line, "<kernel> <grid> <block> <k> <j>" (from vcloak.gpu.kernels.launch_plan).
#include "cuda_shim.h"

#include "bitonic.cu"

#include <cstdio>
#include <cstdlib>
#include <cstring>

int main(int argc, char** argv)
{
    if (argc != 5) {
        return 2;
    }
    u32 n = (u32)strtoul(argv[3], NULL, 10);
    std::vector<u64> hi(n), lo(n);
    std::vector<u32> slot(n), pay(n);
    FILE* f = fopen(argv[1], "rb");
    if (!f || fread(hi.data(), 8, n, f) != n || fread(lo.data(), 8, n, f) != n
        || fread(slot.data(), 4, n, f) != n || fread(pay.data(), 4, n, f) != n) {
        return 3;
    }
    fclose(f);

    FILE* plan = fopen(argv[4], "r");
    if (!plan) {
        return 4;
    }
    char name[64];
    u32 grid, block, k, j;
    while (fscanf(plan, "%63s %u %u %u %u", name, &grid, &block, &k, &j) == 5) {
        if (!strcmp(name, "bitonic_pairs_global")) {
            shim_launch(grid, block,
                        [&] { bitonic_pairs_global(hi.data(), lo.data(), slot.data(), pay.data(), k, j, n / 2); });
        } else if (!strcmp(name, "bitonic_shared")) {
            shim_launch(grid, block, [&] { bitonic_shared(hi.data(), lo.data(), slot.data(), pay.data(), k, j, n); });
        } else if (!strcmp(name, "bitonic_shared_full")) {
            shim_launch(grid, block, [&] { bitonic_shared_full(hi.data(), lo.data(), slot.data(), pay.data(), n); });
        } else {
            return 5;
        }
    }
    fclose(plan);

    f = fopen(argv[2], "wb");
    if (!f || fwrite(hi.data(), 8, n, f) != n || fwrite(lo.data(), 8, n, f) != n
        || fwrite(slot.data(), 4, n, f) != n || fwrite(pay.data(), 4, n, f) != n) {
        return 6;
    }
    fclose(f);
    return 0;
}
