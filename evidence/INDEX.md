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
