// CPU stand-in for the CUDA execution model, so the laptop (no GPU, no nvcc) can compile and run the
// real kernels/*.cu sources. Correctness only: it says nothing about speed or about what nvcc emits.
// One block runs at a time and each of its threads is a Windows fiber. __syncthreads() yields to the
// next thread of the block, so every thread reaches barrier b before any thread passes it.
#pragma once
#include <windows.h>

#include <functional>
#include <vector>

struct shim_uint3 {
    unsigned int x, y, z;
};
static shim_uint3 threadIdx, blockIdx, blockDim, gridDim;

#define __global__
#define __device__
#define __forceinline__ inline
#define __shared__ static  // blocks run one after another, so a static is the running block's shared memory

static LPVOID shim_scheduler;
static const std::function<void()>* shim_kernel;

struct shim_thread {
    LPVOID fiber;
    bool done;
};

static inline void __syncthreads() { SwitchToFiber(shim_scheduler); }

static VOID CALLBACK shim_entry(LPVOID arg)
{
    (*shim_kernel)();
    static_cast<shim_thread*>(arg)->done = true;
    SwitchToFiber(shim_scheduler);  // a fiber routine must not return
}

// Run `kernel` for a grid of `grid` blocks of `block` threads (one-dimensional launches only).
static void shim_launch(unsigned int grid, unsigned int block, const std::function<void()>& kernel)
{
    if (!shim_scheduler) {
        shim_scheduler = ConvertThreadToFiber(NULL);
    }
    shim_kernel = &kernel;
    gridDim = {grid, 1, 1};
    blockDim = {block, 1, 1};
    for (unsigned int b = 0; b < grid; ++b) {
        std::vector<shim_thread> threads(block);
        for (unsigned int t = 0; t < block; ++t) {
            threads[t].done = false;
            threads[t].fiber = CreateFiber(0, shim_entry, &threads[t]);
        }
        for (unsigned int live = block; live > 0;) {
            live = 0;
            for (unsigned int t = 0; t < block; ++t) {
                if (threads[t].done) {
                    continue;
                }
                blockIdx = {b, 0, 0};
                threadIdx = {t, 0, 0};
                SwitchToFiber(threads[t].fiber);
                live += threads[t].done ? 0 : 1;
            }
        }
        for (unsigned int t = 0; t < block; ++t) {
            DeleteFiber(threads[t].fiber);
        }
    }
}
