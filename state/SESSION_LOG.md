# SESSION LOG (append-only; newest at the bottom; format: ai/LOGGING_AND_AUDIT.md §1)

## Session 1 — 2026-10-11 01:48 — M00 Bootstrap & GPU probe — owner:Aditya
- Steps: S1→S6 gate (status after: BLOCKED_HUMAN — GPU JOB READY)
- Did: ran setup/bootstrap.ps1 (venv, packages, git init, identity Aditya); .gitignore; kit committed.
- Did: pyproject.toml, requirements.lock, requirements-gpu.txt, tasks.py, src/vcloak/{config,runs}.py,
  src/vcloak/gpu/{runtime,sim,telemetry}.py, scripts/{gpujob,new_run,check_metrics}.py, tests/unit (5 files).
- Did: kernels/vector_add.cu + bench/probe_gpu.py + bench/jobs/M00.json; packed job 20261011-014756_M00.
- Evidence: runs/20261011-014812_M00_local_checks (pytest 33/33; gpujob round trip + tamper 12/12;
  check_metrics self-test 6/6; real bundle unpacked, dry-run and bundled tests 32 passed/2 skipped).
- Metrics added: none (nothing measurable without the GPU; no numpy number recorded)
- Decisions: none
- Issues: opened ISSUE-2 (GPU JOB READY); opened and closed ISSUE-1 (bootstrap.ps1 BOM)
- Deviations from spec: (a) manifest/run code lives in src/vcloak/runs.py with scripts/new_run.py as its CLI,
  because the runner bundle ships src/ but must write manifests; (b) scripts/ is added to the bundle so the
  bundled tests import; (c) bundle_sha256 is a content hash excluding job.json (a file cannot hold its own hash);
  (d) manifest status gains FAIL; (e) docs/ENV.md and STATE env are deferred to S7 (need the ingested probe).
- Commit: (see next line)
- Next: M00 S6 ingest → S7 → audit ; human action: ISSUE-2
