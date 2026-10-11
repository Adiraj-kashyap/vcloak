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
