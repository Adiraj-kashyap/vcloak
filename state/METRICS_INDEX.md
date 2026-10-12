# METRICS INDEX — every reported number must appear here (format: ai/LOGGING_AND_AUDIT.md §5)

| Metric ID | Value | Unit | Stat | Module | Run dir | Command | Date | Quick | Backend | Runner |
|---|---|---|---|---|---|---|---|---|---|---|
| ENV-PEAK-BW | 320.064 | GB/s | theoretical | M00 | runs/20261011-110031_M00_gpu_probe | python bench/probe_gpu.py --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| ENV-D2D-BW | 238.35 | GB/s | median | M00 | runs/20261011-110031_M00_gpu_probe | python bench/probe_gpu.py --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| ENV-MAX-LOG2N | 24 | log2(n) | value | M00 | runs/20261011-110031_M00_gpu_probe | python bench/probe_gpu.py --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| ENV-VRAM-FREE | 15.42 | GB | value | M00 | runs/20261011-110031_M00_gpu_probe | python bench/probe_gpu.py --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| ENV-PEAK-BW | 320.064 | GB/s | theoretical | M00 | runs/20261011-110133_M00_gpu_probe | python bench/probe_gpu.py --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| ENV-D2D-BW | 238.25 | GB/s | median | M00 | runs/20261011-110133_M00_gpu_probe | python bench/probe_gpu.py --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| ENV-MAX-LOG2N | 24 | log2(n) | value | M00 | runs/20261011-110133_M00_gpu_probe | python bench/probe_gpu.py --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| ENV-VRAM-FREE | 15.42 | GB | value | M00 | runs/20261011-110133_M00_gpu_probe | python bench/probe_gpu.py --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-SMOKE-MS-2^16 | 0.5243 | ms | median | M03 | runs/20261011-122303_M03_bitonic_smoke | python bench/bitonic_smoke.py --seed 3 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-SMOKE-CV-2^16 | 0.0118 | - | cv | M03 | runs/20261011-122303_M03_bitonic_smoke | python bench/bitonic_smoke.py --seed 3 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-RACECHECK-HAZARDS | 0 | count | value | M03 | runs/20261011-122303_M03_bitonic_smoke | python bench/bitonic_smoke.py --seed 3 --out runs | 20261011 | no | cupy | kaggle |
| K-CHACHA-TAGS-SMOKE-GBS-2^20 | 85.0427 | GB/s | median | M04 | runs/20261011-134013_M04_chacha_smoke | python bench/chacha_smoke.py --seed 4 --out runs | 20261011 | no | cupy | kaggle |
| K-CHACHA-TAGS-SMOKE-MS-2^20 | 0.1973 | ms | median | M04 | runs/20261011-134013_M04_chacha_smoke | python bench/chacha_smoke.py --seed 4 --out runs | 20261011 | no | cupy | kaggle |
| K-CHACHA-TAGS-SMOKE-CV-2^20 | 0.083 | - | cv | M04 | runs/20261011-134013_M04_chacha_smoke | python bench/chacha_smoke.py --seed 4 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-MS-S64 | 1.5749 | ms | median | M06 | runs/20261011-163049_M06_pipeline_smoke_quick | python bench/run_pipeline.py --dev --seed 6 --quick --out runs | 20261011 | yes | cupy | kaggle |
| P-WRITE-EPOCH-MS-S4096 | 10.8422 | ms | median | M06 | runs/20261011-163049_M06_pipeline_smoke_quick | python bench/run_pipeline.py --dev --seed 6 --quick --out runs | 20261011 | yes | cupy | kaggle |
| P-WRITE-EPOCH-MS-S65536 | 208.1128 | ms | median | M06 | runs/20261011-163049_M06_pipeline_smoke_quick | python bench/run_pipeline.py --dev --seed 6 --quick --out runs | 20261011 | yes | cupy | kaggle |
| P-READ-WINDOW-MS-K128 | 0.5045 | ms | median | M06 | runs/20261011-163049_M06_pipeline_smoke_quick | python bench/run_pipeline.py --dev --seed 6 --quick --out runs | 20261011 | yes | cupy | kaggle |
| P-READ-WINDOW-MS-K1024 | 0.5821 | ms | median | M06 | runs/20261011-163049_M06_pipeline_smoke_quick | python bench/run_pipeline.py --dev --seed 6 --quick --out runs | 20261011 | yes | cupy | kaggle |
| K-BITONIC-GLOBAL-MS-2^10 | 0.68178 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-BW-PCT-2^10 | 1.239 | % | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-GLOBAL-MS-2^11 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-BW-PCT-2^11 | UNSTABLE | % | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-GLOBAL-MS-2^12 | 0.91856 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-BW-PCT-2^12 | 5.216 | % | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-GLOBAL-MS-2^13 | 1.06283 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-BW-PCT-2^13 | 10.519 | % | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-GLOBAL-MS-2^14 | 1.21144 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-BW-PCT-2^14 | 21.297 | % | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-GLOBAL-MS-2^15 | 1.41499 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-BW-PCT-2^15 | 41.676 | % | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-GLOBAL-MS-2^16 | 1.5785 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-BW-PCT-2^16 | 84.68 | % | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-GLOBAL-MS-2^17 | 1.7951 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-BW-PCT-2^17 | 167.539 | % | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-GLOBAL-MS-2^18 | 9.53584 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-BW-PCT-2^18 | 70.499 | % | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-GLOBAL-MS-2^19 | 21.01866 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-BW-PCT-2^19 | 71.076 | % | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-GLOBAL-MS-2^20 | 45.25702 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-BW-PCT-2^20 | 72.969 | % | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-GLOBAL-MS-2^21 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-BW-PCT-2^21 | UNSTABLE | % | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-GLOBAL-MS-2^22 | 215.88358 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-BW-PCT-2^22 | 73.717 | % | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-FUSED-MS-2^10 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-FUSED-MS-2^11 | 0.08602 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-FUSED-MS-2^12 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-FUSED-MS-2^13 | 0.19534 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-FUSED-MS-2^14 | 0.25667 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-FUSED-MS-2^15 | 0.34539 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-FUSED-MS-2^16 | 0.44131 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-FUSED-MS-2^17 | 0.68448 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-FUSED-MS-2^18 | 3.53085 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-FUSED-MS-2^19 | 8.3375 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-FUSED-MS-2^20 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-FUSED-MS-2^21 | 44.1549 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-FUSED-MS-2^22 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-E2E-MS-2^10 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-E2E-MS-2^11 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-E2E-MS-2^12 | 0.21541 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-E2E-MS-2^13 | 0.29192 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-E2E-MS-2^14 | 0.37426 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-E2E-MS-2^15 | 0.49842 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-E2E-MS-2^16 | 0.70379 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-E2E-MS-2^17 | 1.21435 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-E2E-MS-2^18 | 4.54963 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-E2E-MS-2^19 | 10.1008 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-E2E-MS-2^20 | 22.78474 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-E2E-MS-2^21 | 51.89888 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BITONIC-E2E-MS-2^22 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-CHACHA-MS-2^10 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-CHACHA-MS-2^11 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-CHACHA-MS-2^12 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-CHACHA-MS-2^13 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-CHACHA-MS-2^14 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-CHACHA-MS-2^15 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-CHACHA-MS-2^16 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-CHACHA-MS-2^17 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-CHACHA-MS-2^18 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-CHACHA-MS-2^19 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-CHACHA-MS-2^20 | 0.15318 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-CHACHA-MS-2^21 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-CHACHA-MS-2^22 | 0.54322 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-AEADOPEN-MS-2^10 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-AEADOPEN-MS-2^11 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-AEADOPEN-MS-2^12 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-AEADOPEN-MS-2^13 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-AEADOPEN-MS-2^14 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-AEADOPEN-MS-2^15 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-AEADOPEN-MS-2^16 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-AEADOPEN-MS-2^17 | 0.10854 | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-AEADOPEN-MS-2^18 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-AEADOPEN-MS-2^19 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-AEADOPEN-MS-2^20 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-AEADOPEN-MS-2^21 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-AEADOPEN-MS-2^22 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BUCKETPRF-MS-2^10 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BUCKETPRF-MS-2^11 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BUCKETPRF-MS-2^12 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BUCKETPRF-MS-2^13 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BUCKETPRF-MS-2^14 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BUCKETPRF-MS-2^15 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BUCKETPRF-MS-2^16 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BUCKETPRF-MS-2^17 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BUCKETPRF-MS-2^18 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BUCKETPRF-MS-2^19 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BUCKETPRF-MS-2^20 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BUCKETPRF-MS-2^21 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BUCKETPRF-MS-2^22 | UNSTABLE | ms | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-CHACHA-GBS | 123.5399 | GB/s | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-AEADOPEN-ROWS-S | UNSTABLE | rows/s | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| K-BUCKETPRF-ROWS-S | UNSTABLE | rows/s | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| TEL-SMCLK-MEDIAN | 1125.0 | MHz | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| TEL-POWER-W-MEDIAN | 66.37 | W | median | M07 | runs/20261011-213207_M07_kernel_sweep | python bench/run_kernels.py --part gpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-MS-2^10 | 4.9578 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-MS-2^11 | 7.8198 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-MS-2^12 | 15.605 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-MS-2^13 | 30.4625 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-MS-2^14 | 65.0011 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-MS-2^15 | 141.5689 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-MS-2^16 | 327.8493 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-MS-2^17 | 755.197 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-MS-2^18 | 1833.8399 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-MS-2^19 | 4176.3912 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-MS-2^20 | 10197.3165 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-MS-2^21 | 23880.4544 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-MS-2^22 | 56582.6164 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-VIEWS-MS-2^10 | 4.7741 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-VIEWS-MS-2^11 | 8.0416 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-VIEWS-MS-2^12 | 13.8352 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-VIEWS-MS-2^13 | 27.3125 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-VIEWS-MS-2^14 | 54.6554 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-VIEWS-MS-2^15 | 111.5482 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-VIEWS-MS-2^16 | 244.8571 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-VIEWS-MS-2^17 | 541.7404 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-VIEWS-MS-2^18 | 1211.6883 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-VIEWS-MS-2^19 | 2684.1608 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-VIEWS-MS-2^20 | 6280.6001 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-VIEWS-MS-2^21 | 14680.271 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-VIEWS-MS-2^22 | 35064.9909 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-NUMBA-MS-2^10 | 1.1046 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-NUMBA-MS-2^11 | 1.5905 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-NUMBA-MS-2^12 | 2.3797 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-NUMBA-MS-2^13 | 3.7553 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-NUMBA-MS-2^14 | 6.3921 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-NUMBA-MS-2^15 | 14.1079 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-NUMBA-MS-2^16 | 24.3463 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-NUMBA-MS-2^17 | 52.0377 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-NUMBA-MS-2^18 | 105.3083 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-NUMBA-MS-2^19 | 232.8735 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-NUMBA-MS-2^20 | 495.7042 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-NUMBA-MS-2^21 | 1090.2056 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-BITONIC-NUMBA-MS-2^22 | 2416.3105 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-LEXSORT-MS-2^10 | 0.1099 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-LEXSORT-MS-2^11 | 0.2453 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-LEXSORT-MS-2^12 | 0.5457 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-LEXSORT-MS-2^13 | 1.1821 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-LEXSORT-MS-2^14 | 2.6361 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-LEXSORT-MS-2^15 | 5.8483 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-LEXSORT-MS-2^16 | 11.8345 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-LEXSORT-MS-2^17 | 26.9152 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-LEXSORT-MS-2^18 | 61.2783 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-LEXSORT-MS-2^19 | 132.202 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-LEXSORT-MS-2^20 | 287.8445 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-LEXSORT-MS-2^21 | 671.7223 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| CPU-LEXSORT-MS-2^22 | 1559.4714 | ms | median | M07 | runs/20261011-213731_M07_cpu_baselines | python bench/run_kernels.py --part cpu --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| X-CROSSOVER-N | UNSTABLE | n | upper-bound | M07 | runs/20261011-215652_M07_crossover | python bench/run_kernels.py --part crossover --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| X-SPEEDUP-2^16 | 34.593 | x | ratio | M07 | runs/20261011-215652_M07_crossover | python bench/run_kernels.py --part crossover --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| X-SPEEDUP-2^20 | 21.756 | x | ratio | M07 | runs/20261011-215652_M07_crossover | python bench/run_kernels.py --part crossover --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| X-SPEEDUP-VS-LEXSORT-2^16 | 16.815 | x | ratio | M07 | runs/20261011-215652_M07_crossover | python bench/run_kernels.py --part crossover --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| X-SPEEDUP-VS-LEXSORT-2^20 | 12.633 | x | ratio | M07 | runs/20261011-215652_M07_crossover | python bench/run_kernels.py --part crossover --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-P99-S64 | 1.1208 | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-MS-S64 | 0.8858 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-DEVICE-MS-S64 | 0.6848 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-DEVICE-P99-S64 | 0.8987 | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-HOST-MS-S64 | 0.1977 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-P99-S1024 | UNSTABLE | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-MS-S1024 | UNSTABLE | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-DEVICE-MS-S1024 | UNSTABLE | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-DEVICE-P99-S1024 | UNSTABLE | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-HOST-MS-S1024 | UNSTABLE | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-P99-S4096 | UNSTABLE | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-MS-S4096 | UNSTABLE | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-DEVICE-MS-S4096 | UNSTABLE | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-DEVICE-P99-S4096 | UNSTABLE | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-HOST-MS-S4096 | UNSTABLE | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-P99-S16384 | UNSTABLE | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-MS-S16384 | UNSTABLE | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-DEVICE-MS-S16384 | UNSTABLE | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-DEVICE-P99-S16384 | UNSTABLE | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-HOST-MS-S16384 | UNSTABLE | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-P99-S65536 | 279.5451 | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-MS-S65536 | 242.3974 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-DEVICE-MS-S65536 | 8.7638 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-DEVICE-P99-S65536 | 11.0996 | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-WRITE-EPOCH-HOST-MS-S65536 | 233.7088 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-P99-K64 | 0.5421 | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-MS-K64 | 0.4308 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-DEVICE-MS-K64 | 0.4269 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-DEVICE-P99-K64 | 0.5385 | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-HOST-MS-K64 | 0.0037 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-P99-K128 | 0.5564 | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-MS-K128 | 0.4448 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-DEVICE-MS-K128 | 0.4399 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-DEVICE-P99-K128 | 0.552 | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-HOST-MS-K128 | 0.0041 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-P99-K256 | 0.5703 | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-MS-K256 | 0.4423 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-DEVICE-MS-K256 | 0.4366 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-DEVICE-P99-K256 | 0.56 | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-HOST-MS-K256 | 0.0055 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-P99-K512 | 0.6067 | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-MS-K512 | 0.4592 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-DEVICE-MS-K512 | 0.4507 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-DEVICE-P99-K512 | 0.5974 | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-HOST-MS-K512 | 0.0083 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-P99-K1024 | 0.6271 | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-MS-K1024 | 0.5095 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-DEVICE-MS-K1024 | 0.4964 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-DEVICE-P99-K1024 | 0.6144 | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-HOST-MS-K1024 | 0.013 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-P99-K2048 | 0.7119 | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-MS-K2048 | 0.5656 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-DEVICE-MS-K2048 | 0.5452 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-DEVICE-P99-K2048 | 0.6892 | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-HOST-MS-K2048 | 0.0203 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-P99-K4096 | 0.8954 | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-MS-K4096 | 0.689 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-DEVICE-MS-K4096 | 0.6505 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-DEVICE-P99-K4096 | 0.8604 | ms | p99 | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| P-READ-WINDOW-HOST-MS-K4096 | 0.0363 | ms | median | M07 | runs/20261011-215653_M07_pipeline | python bench/run_pipeline.py --dev --full --seed 7 --out runs | 20261011 | no | cupy | kaggle |
| T-DUDECT-MAXT-CONTROL-LEAK | 376.9125 | - | max abs(t) | M08 | runs/20261012-031245_M08_dudect_selftest_quick | python bench/run_dudect.py --targets controls --seed 8 --quick --name dudect_selftest --out runs | 20261012 | yes | cupy | kaggle |
| T-DUDECT-N-CONTROL-LEAK | 10000 | measurements | per class | M08 | runs/20261012-031245_M08_dudect_selftest_quick | python bench/run_dudect.py --targets controls --seed 8 --quick --name dudect_selftest --out runs | 20261012 | yes | cupy | kaggle |
| T-DUDECT-MAXT-CONTROL-NULL | 1.933 | - | max abs(t) | M08 | runs/20261012-031245_M08_dudect_selftest_quick | python bench/run_dudect.py --targets controls --seed 8 --quick --name dudect_selftest --out runs | 20261012 | yes | cupy | kaggle |
| T-DUDECT-N-CONTROL-NULL | 10000 | measurements | per class | M08 | runs/20261012-031245_M08_dudect_selftest_quick | python bench/run_dudect.py --targets controls --seed 8 --quick --name dudect_selftest --out runs | 20261012 | yes | cupy | kaggle |
| T-DUDECT-MAXT-CONTROL-NULL | 2.0786 | - | max abs(t) | M08 | runs/20261012-031331_M08_dudect | python bench/run_dudect.py --targets control_null,targets --seed 8 --out runs | 20261012 | no | cupy | kaggle |
| T-DUDECT-N-CONTROL-NULL | 100000 | measurements | per class | M08 | runs/20261012-031331_M08_dudect | python bench/run_dudect.py --targets control_null,targets --seed 8 --out runs | 20261012 | no | cupy | kaggle |
| T-DUDECT-MAXT-BITONIC-EQUAL | 1.2708 | - | max abs(t) | M08 | runs/20261012-031331_M08_dudect | python bench/run_dudect.py --targets control_null,targets --seed 8 --out runs | 20261012 | no | cupy | kaggle |
| T-DUDECT-N-BITONIC-EQUAL | 100000 | measurements | per class | M08 | runs/20261012-031331_M08_dudect | python bench/run_dudect.py --targets control_null,targets --seed 8 --out runs | 20261012 | no | cupy | kaggle |
| T-DUDECT-MAXT-BITONIC-SORTED | 2.6965 | - | max abs(t) | M08 | runs/20261012-031331_M08_dudect | python bench/run_dudect.py --targets control_null,targets --seed 8 --out runs | 20261012 | no | cupy | kaggle |
| T-DUDECT-N-BITONIC-SORTED | 100000 | measurements | per class | M08 | runs/20261012-031331_M08_dudect | python bench/run_dudect.py --targets control_null,targets --seed 8 --out runs | 20261012 | no | cupy | kaggle |
| T-DUDECT-MAXT-WRITE-EPOCH | 2.7559 | - | max abs(t) | M08 | runs/20261012-031331_M08_dudect | python bench/run_dudect.py --targets control_null,targets --seed 8 --out runs | 20261012 | no | cupy | kaggle |
| T-DUDECT-MAXT-WRITE-EPOCH-CALL | 8.2776 | - | max abs(t) | M08 | runs/20261012-031331_M08_dudect | python bench/run_dudect.py --targets control_null,targets --seed 8 --out runs | 20261012 | no | cupy | kaggle |
| T-DUDECT-N-WRITE-EPOCH | 100000 | measurements | per class | M08 | runs/20261012-031331_M08_dudect | python bench/run_dudect.py --targets control_null,targets --seed 8 --out runs | 20261012 | no | cupy | kaggle |
| T-DUDECT-MAXT-AEAD-TAG | 6.2415 | - | max abs(t) | M08 | runs/20261012-031331_M08_dudect | python bench/run_dudect.py --targets control_null,targets --seed 8 --out runs | 20261012 | no | cupy | kaggle |
| T-DUDECT-N-AEAD-TAG | 100000 | measurements | per class | M08 | runs/20261012-031331_M08_dudect | python bench/run_dudect.py --targets control_null,targets --seed 8 --out runs | 20261012 | no | cupy | kaggle |
| T-DUDECT-MAXT-AEAD-CONV | 11.6369 | - | max abs(t) | M08 | runs/20261012-031331_M08_dudect | python bench/run_dudect.py --targets control_null,targets --seed 8 --out runs | 20261012 | no | cupy | kaggle |
| T-DUDECT-N-AEAD-CONV | 100000 | measurements | per class | M08 | runs/20261012-031331_M08_dudect | python bench/run_dudect.py --targets control_null,targets --seed 8 --out runs | 20261012 | no | cupy | kaggle |
| T-SASS-BRA-BITONIC-SHARED-FULL | 6 | branches | count | M08 | runs/20261012-040020_M08_sass | python scripts/sass_check.py --compile --out runs | 20261012 | no | cupy | kaggle |
| T-SASS-BRA-BITONIC-SHARED | 4 | branches | count | M08 | runs/20261012-040020_M08_sass | python scripts/sass_check.py --compile --out runs | 20261012 | no | cupy | kaggle |
| T-SASS-BRA-BITONIC-PAIRS-GLOBAL | 2 | branches | count | M08 | runs/20261012-040020_M08_sass | python scripts/sass_check.py --compile --out runs | 20261012 | no | cupy | kaggle |
| T-SASS-BRA-AEAD-OPEN-SEQ | 4 | branches | count | M08 | runs/20261012-040020_M08_sass | python scripts/sass_check.py --compile --out runs | 20261012 | no | cupy | kaggle |
| T-SASS-BRA-CHACHA-TAGS | 3 | branches | count | M08 | runs/20261012-040020_M08_sass | python scripts/sass_check.py --compile --out runs | 20261012 | no | cupy | kaggle |
| T-SASS-BRA-CHACHA-BLOCKS | 3 | branches | count | M08 | runs/20261012-040020_M08_sass | python scripts/sass_check.py --compile --out runs | 20261012 | no | cupy | kaggle |
| T-NCU-DIVERGENT-BITONIC-PAIRS-GLOBAL | NOT_MEASURED | branches | sum | M08 | runs/20261012-040027_M08_ncu | python bench/run_ncu.py --seed 8 --out runs | 20261012 | no | cupy | kaggle |
| T-NCU-BRANCHEFF-BITONIC-PAIRS-GLOBAL | NOT_MEASURED | % | ratio of sums | M08 | runs/20261012-040027_M08_ncu | python bench/run_ncu.py --seed 8 --out runs | 20261012 | no | cupy | kaggle |
| T-NCU-DIVERGENT-BITONIC-SHARED | NOT_MEASURED | branches | sum | M08 | runs/20261012-040027_M08_ncu | python bench/run_ncu.py --seed 8 --out runs | 20261012 | no | cupy | kaggle |
| T-NCU-BRANCHEFF-BITONIC-SHARED | NOT_MEASURED | % | ratio of sums | M08 | runs/20261012-040027_M08_ncu | python bench/run_ncu.py --seed 8 --out runs | 20261012 | no | cupy | kaggle |
| T-NCU-DIVERGENT-BITONIC-SHARED-FULL | NOT_MEASURED | branches | sum | M08 | runs/20261012-040027_M08_ncu | python bench/run_ncu.py --seed 8 --out runs | 20261012 | no | cupy | kaggle |
| T-NCU-BRANCHEFF-BITONIC-SHARED-FULL | NOT_MEASURED | % | ratio of sums | M08 | runs/20261012-040027_M08_ncu | python bench/run_ncu.py --seed 8 --out runs | 20261012 | no | cupy | kaggle |
| T-NCU-DIVERGENT-AEAD-OPEN-SEQ | NOT_MEASURED | branches | sum | M08 | runs/20261012-040027_M08_ncu | python bench/run_ncu.py --seed 8 --out runs | 20261012 | no | cupy | kaggle |
| T-NCU-BRANCHEFF-AEAD-OPEN-SEQ | NOT_MEASURED | % | ratio of sums | M08 | runs/20261012-040027_M08_ncu | python bench/run_ncu.py --seed 8 --out runs | 20261012 | no | cupy | kaggle |
