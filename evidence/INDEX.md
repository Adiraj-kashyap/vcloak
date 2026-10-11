# EVIDENCE INDEX — every screenshot, figure and capture, with where it came from
#
# Maintained by scripts/capture_evidence.py and the `capture-evidence` skill. Do not hand-edit rows.
# Rules in ai/EVIDENCE.md. A row with no run dir is not evidence.

| ID | What it shows | Module | Date | Source run | Data state | Used in |
|---|---|---|---|---|---|---|
| GPU-M00-SMI | gpu/M00_nvidia_smi.txt — nvidia-smi on the runner: Tesla T4, driver 580.82.07 | M00 | 2026-10-11 | runs/20261011-110133_M00_gpu_probe (git a45088b) | measured | — |
| GPU-M00-PROBE | gpu/M00_device_probe.json — device properties, vector-add result, D2D copy bandwidth, ENV metrics | M00 | 2026-10-11 | runs/20261011-110133_M00_gpu_probe (git a45088b) | measured | — |
| TERM-M00-PYTEST | terminal/M00_pytest.txt — local pytest summary, numpy backend, no GPU | M00 | 2026-10-11 | runs/20261011-163648_M00_ingest_checks (git d721f72, dirty) | measured | — |
| TERM-M00-GATES | terminal/M00_probe_gates.txt — acceptance gates applied to both ingested probe runs | M00 | 2026-10-11 | runs/20261011-163648_M00_ingest_checks (git d721f72, dirty) | measured | — |
| TERM-M00-AUDIT | terminal/M00_audit.txt — M00 audit table A1–A5, G1–G10 | M00 | 2026-10-11 | runs/20261011-163648_M00_ingest_checks (git d721f72, dirty) | measured | — |
| GPU-M03-SMI | gpu/M03_nvidia_smi.txt — nvidia-smi on the runner at the start of the M03 job | M03 | 2026-10-11 | gpujobs/out/20261011-173759_M03/logs (job 20261011-173759_M03, git d91bfd6) | measured | — |
| GPU-M03-SMOKE | gpu/M03_bitonic_smoke_summary.json — bitonic sort at n = 2^16 on the T4: 0 mismatches, smoke timing (not an M07 result), launch plan, racecheck block | M03 | 2026-10-11 | runs/20261011-122303_M03_bitonic_smoke (git d91bfd6) | measured | — |
| GPU-M03-RACE | gpu/M03_racecheck.txt — compute-sanitizer racecheck summary, n = 2^12: 0 hazards | M03 | 2026-10-11 | runs/20261011-122303_M03_bitonic_smoke (git d91bfd6) | measured | — |
| TERM-M03-GPUTESTS | terminal/M03_gpu_tests.txt — pytest on the T4 (bit-exact vs oracle and twin, incl. 2^24) and the smoke script output | M03 | 2026-10-11 | gpujobs/out/20261011-173759_M03/logs (job 20261011-173759_M03, git d91bfd6) | measured | — |
| TERM-M03-GATES | terminal/M03_gates.txt — S6 acceptance gates applied to the ingested run | M03 | 2026-10-11 | runs/20261011-181052_M03_ingest_audit (git b6fe20d, dirty) | measured | — |
| TERM-M03-AUDIT | terminal/M03_audit.txt — M03 audit table A1–A4, G1–G10 | M03 | 2026-10-11 | runs/20261011-181052_M03_ingest_audit (git b6fe20d, dirty) | measured | — |
| GPU-M04-SMI | gpu/M04_nvidia_smi.txt — nvidia-smi on the runner at the start of the M04 job | M04 | 2026-10-11 | gpujobs/out/20261011-183051_M04/logs (job 20261011-183051_M04, git 680c28d) | measured | — |
| GPU-M04-SMOKE | gpu/M04_chacha_smoke_summary.json — ChaCha20 tag generation at n = 2^20 on the T4: 0 mismatches, smoke timing at a low SM clock (not an M07 result), both clock snapshots | M04 | 2026-10-11 | runs/20261011-134013_M04_chacha_smoke (git 680c28d) | measured | — |
| TERM-M04-GPUTESTS | terminal/M04_gpu_tests.txt — pytest on the T4 (RFC 8439 vectors, bit-exact vs M02 and twin, incl. 2^24), bitonic regression, smoke output, check_oblivious | M04 | 2026-10-11 | gpujobs/out/20261011-183051_M04/logs (job 20261011-183051_M04, git 680c28d) | measured | — |
| TERM-M04-GATES | terminal/M04_gates.txt — S4 acceptance gates applied to the ingested run | M04 | 2026-10-11 | runs/20261011-191448_M04_ingest_audit (git 462bf09, dirty) | measured | — |
| TERM-M04-AUDIT | terminal/M04_audit.txt — M04 audit table A1–A4, G1–G10 | M04 | 2026-10-11 | runs/20261011-191448_M04_ingest_audit (git 462bf09, dirty) | measured | — |
| GPU-M05-SMI | gpu/M05_nvidia_smi.txt — nvidia-smi on the runner at the start of the M05 job | M05 | 2026-10-11 | gpujobs/out/20261011-193547_M05/logs (job 20261011-193547_M05, git 69a2cc3) | measured | — |
| TERM-M05-GPUTESTS | terminal/M05_gpu_tests.txt — pytest on the T4 (RFC 8439 Poly1305 and AEAD vectors, seal/open bit-exact vs the reference incl. tamper cases, restore and compaction vs the oracle, GPU = twin, incl. 2^24), ChaCha/bitonic regression, check_oblivious | M05 | 2026-10-11 | gpujobs/out/20261011-193547_M05/logs (job 20261011-193547_M05, git 69a2cc3) | measured | — |
| TERM-M05-GATES | terminal/M05_gates.txt — acceptance gates A1, A2, A4, G5 applied to the ingested logs | M05 | 2026-10-11 | runs/20261011-213200_M05_ingest_audit (git daa83e1, dirty) | measured | — |
| TERM-M05-AUDIT | terminal/M05_audit.txt — M05 audit table A1–A4, G1–G10 | M05 | 2026-10-11 | runs/20261011-213200_M05_ingest_audit (git daa83e1, dirty) | measured | — |
