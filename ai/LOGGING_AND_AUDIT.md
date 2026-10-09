# LOGGING AND AUDIT

## 1. SESSION_LOG entry (append to `state/SESSION_LOG.md`, ≤25 lines)
```
## Session <N> — <YYYY-MM-DD HH:MM> — <Mxx> <title> — owner:<name>
- Steps: S<a>→S<b> (status after: IN_PROGRESS | AUDIT_PENDING | DONE | BLOCKED_*)
- Did: <1–4 bullets, concrete: files created/changed>
- Evidence: runs/<dir>, tests/<path> (<passed>/<total>)
- Metrics added: <METRIC-IDs> (see METRICS_INDEX)
- Decisions: <ADR-ids or "none">
- Issues: opened <ISSUE-ids>, closed <ISSUE-ids>
- Deviations from spec: <none | what and why (+ Amendments note)>
- Commit: <hash>
- Next: <Mxx S<n>> ; human action: <none | ISSUE-id>
```

## 2. Run manifest (`runs/<YYYYMMDD-HHMMSS>_<Mxx>_<name>/manifest.json`)
```json
{
  "run_id": "20261001-143012_M07_bitonic_sweep",
  "module": "M07", "step": "S3", "owner": "Aditya",
  "git_sha": "<git rev-parse HEAD>", "dirty": false,
  "command": "python bench/run_kernels.py --sweep 10:22 --runs 50 --seed 7",
  "seed": 7, "quick": false,
  "params": {"n_log2": [10, 22], "runs": 50, "warmup": 10},
  "env": {"os": "...", "python": "...", "gpu": "...", "cc": "8.6", "driver": "...", "cuda": "...", "cupy": "...", "power_source": "AC"},
  "telemetry_start": {...}, "telemetry_end": {...},
  "outputs": ["raw.csv", "summary.json", "telemetry.csv", "plot.png"],
  "status": "OK | UNSTABLE | NOT_MEASURED",
  "notes": ""
}
```

## 3. Global audit checks (apply to every module)
| ID | Check | How to verify (command / evidence) |
|---|---|---|
| G1 | All module tests pass in a fresh process | `pytest -q <paths> > runs/<dir>/pytest.txt; tail -n 3` shows 0 failed |
| G2 | No fabricated numbers | Every number in files changed this module appears in METRICS_INDEX with an existing run dir: `python scripts/check_metrics.py` (created in M00) |
| G3 | Obliviousness rules | `python scripts/check_oblivious.py kernels/` (created in M03) finds no secret-indexed branch/address patterns; manual notes for anything flagged |
| G4 | Secrets hygiene | `python scripts/check_secrets.py` (created in M02) finds no key-like hex/base64 blobs in the repo, logs or runs; no `secrets/` tracked by git |
| G5 | Bit-exactness vs reference (if the module has a GPU twin of a CPU reference) | GPU tests compare byte-for-byte with the `*_ref` functions over ≥3 sizes and ≥3 seeds |
| G6 | Deliverables exist | Every path in the module's *Deliverables* exists (`ls`); docs updated |
| G7 | Git hygiene | Clean tree after commit; message format correct; `[owner:<name>]` present |
| G8 | State correctness | STATE.md status, step, next_unit and sessions_used are consistent with this log |
| G9 | Logs written | SESSION_LOG entry and AUDIT_LOG entry exist; ISSUES updated |
| G10 | Reproducibility | Each run dir has a manifest with git_sha, seed, command and env; re-running the command in quick mode reproduces the same PASS/FAIL outcome |

## 4. AUDIT_LOG entry (append to `state/AUDIT_LOG.md`)
```
## Audit <Mxx> — <date> — session <N> — result: PASS | FAIL
| Item | Result | Evidence |
|---|---|---|
| A1 <module item> | PASS | runs/... |
| ... |
| G1 | PASS | runs/.../pytest.txt (42/42) |
| ... G10 |
Notes: <anything flagged, N/A justifications>
```

## 5. METRICS_INDEX row (append to `state/METRICS_INDEX.md`)
```
| <METRIC-ID> | <value> | <unit> | <stat: median/p95/...> | <Mxx> | runs/<dir> | <short command> | <date> | <quick?> |
```
Metric ID scheme: `<AREA>-<NAME>[-<param>]`, e.g. `K-BITONIC-MS-2^16`, `P-WRITE-EPOCH-P99-S65536`,
`S-TURNACC-W60`, `S-CHI2-P`, `T-DUDECT-T-BITONIC`, `E2E-P99-U100-VCLOAK`, `ENV-PEAK-BW`.

## 6. Issues (`state/ISSUES.md`)
```
### ISSUE-<n> [OPEN|CLOSED <hash>] <title>
BLOCKS: <Mxx|none>   SEVERITY: low|medium|high   OPENED: <date> session <N>
<3–6 lines: symptom, cause if known, what was tried, proposed fix / options>
```
