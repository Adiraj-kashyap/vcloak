// M00 probe kernel: proves that the runner compiles and executes a CUDA kernel correctly.
// NumPy twin: vcloak.gpu.sim.vector_add. Public inputs only; the branch depends on the thread id and n.
extern "C" __global__
void vector_add(const unsigned int* a, const unsigned int* b, unsigned int* out, unsigned int n)
{
    unsigned int t = blockIdx.x * blockDim.x + threadIdx.x;
    if (t < n) {
        out[t] = a[t] + b[t];
    }
}
