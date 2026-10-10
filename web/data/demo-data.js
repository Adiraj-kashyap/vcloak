/* web/data/demo-data.js — OFFLINE FALLBACK ONLY.
 *
 * Loaded as a plain script (not fetched) so the app also works from file://, where
 * browsers block fetch() of local files.
 *
 * Every number here came from the CPU reference oracle (seed/vcloak_oracle.py), NOT from
 * this build and NOT from a GPU. It is labelled `source: "seed-oracle"` and the UI shows a
 * SEED chip on anything that carries it. Once the real pipeline runs, scripts/export_dashboard.py
 * overwrites web/data/dashboard.json and the live app prefers that; this file stays as the
 * demo-mode fallback. Never add a number here by hand (ADR-013).
 */
window.VCLOAK_DEMO = {
  dashboard: {
    generated_at: "2026-10-10T00:00:00Z",
    git_sha: "seed",
    source: "seed-oracle",
    provenance: {
      backend: "numpy (CPU reference oracle)",
      runner: "none — no GPU measurement yet",
      session_id: "seed",
      note: "Security statistics are machine-independent. All GPU performance figures are still unmeasured."
    },

    tiles: [
      { id: "t-turnacc-conv", label: "Turn order recovered — conventional schema",
        value: 100.0, unit: "%", sub: "every reply pair ordered correctly", state: "crit",
        metric_id: "S-TURNACC-CONVENTIONAL", run: "seed/oracle", quick: false },
      { id: "t-turnacc-r1", label: "Turn order recovered — Review-1 design",
        value: 98.3, unit: "%", sub: "200 ms rounds leaked across epochs", state: "crit",
        metric_id: "S-TURNACC-EPOCH", run: "seed/oracle", quick: false },
      { id: "t-turnacc-w300", label: "Turn order recovered — refined, W = 300 s",
        value: 50.7, unit: "%", sub: "50% is a coin flip", state: "good",
        metric_id: "S-TURNACC-W300", run: "seed/oracle", quick: false },
      { id: "t-restore", label: "Conversations restored in exact order",
        value: "60 / 60", unit: "", sub: "including shared buckets and dummies", state: "good",
        metric_id: "S-E0-RESTORE", run: "seed/oracle", quick: false },
      { id: "t-chi2", label: "Permutation uniformity (χ² p-value)",
        value: 0.152, unit: "", sub: "ideal sampler scores 0.098 on the same test", state: "good",
        metric_id: "S-CHI2-P", run: "seed/oracle", quick: false },
      { id: "t-trace", label: "Distinct comparator traces (5 adversarial inputs)",
        value: 1, unit: "", sub: "merge sort produces 4 — its pattern leaks", state: "good",
        metric_id: "S-TRACE-DISTINCT", run: "seed/oracle", quick: false },
      { id: "t-e5", label: "Session-security scenarios behaving as expected",
        value: "12 / 12", unit: "", sub: "replay, theft, rotation, tampering", state: "good",
        metric_id: "SEC-E5-PASS", run: "seed/oracle", quick: false },
      { id: "t-kernel", label: "Bitonic permute, 2^16 slots (GPU)",
        value: null, unit: "ms", state: "na", metric_id: "K-BITONIC-FUSED-MS-2^16",
        how: "M07 · pack the kernel sweep job and run it on Colab or Kaggle" },
      { id: "t-dudect", label: "dudect max |t| (timing leakage)",
        value: null, unit: "", state: "na", metric_id: "T-DUDECT-MAXT-BITONIC",
        how: "M08 · needs a long runner session (|t| < 4.5 means no evidence of leakage)" },
      { id: "t-crossover", label: "GPU beats the CPU above n =",
        value: null, unit: "", state: "na", metric_id: "X-CROSSOVER-N",
        how: "M07 · GPU and CPU baselines must come from the same runner session" }
    ],

    charts: [
      {
        id: "attack_ablation", kind: "groupedBar",
        title: "Order-recovery attack vs visible window",
        note: "Turn-order accuracy: for two consecutive messages in a conversation, does the dump order them correctly? The attacker is even told which rows belong to which conversation.",
        categories: ["Conventional", "Review-1", "W = 1 s", "W = 10 s", "W = 60 s", "W = 300 s"],
        series: [
          { name: "Measured", slot: 1, values: [100.0, 98.3, 92.1, 68.5, 56.0, 50.7] },
          { name: "Predicted 1 − f/2", slot: 3, values: [92.2, 98.1, 92.2, 68.5, 55.6, 50.8] }
        ],
        unit: "%", yMin: 40, yMax: 100,
        refLine: { value: 50, label: "chance" },
        metric_ids: ["S-TURNACC-CONVENTIONAL", "S-TURNACC-EPOCH", "S-TURNACC-W1", "S-TURNACC-W10", "S-TURNACC-W60", "S-TURNACC-W300"],
        runs: ["seed/oracle"]
      },
      {
        id: "tau_hist", kind: "histogram",
        title: "Per-epoch Kendall τ, in units of σ",
        note: "1,000 epochs at 65,536 slots. A uniform shuffle puts 99.73% inside ±3σ; we measured 99.6%, which is ordinary sampling noise.",
        binCenters: [-3.83,-3.50,-3.17,-2.83,-2.50,-2.17,-1.83,-1.50,-1.17,-0.83,-0.50,-0.17,0.17,0.50,0.83,1.17,1.50,1.83,2.17,2.50,2.83,3.17,3.50,3.83],
        counts: [0,0,3,0,5,16,21,44,59,98,140,128,119,107,92,71,52,17,17,9,1,1,0,0],
        band: 3, xLabel: "τ / σ", yLabel: "epochs",
        metric_ids: ["S-TAUBAND-PCT", "S-TAU-SIGMA-MEAS"], runs: ["seed/oracle"]
      },
      {
        id: "tau_layouts", kind: "groupedBar",
        title: "Kendall τ inside a visible round",
        note: "Within a round, order carries no information in any V-cloak layout — the shuffle itself works. The leak the attack found was between rounds, not inside them.",
        categories: ["Conventional", "Review-1", "W = 1 s", "W = 10 s", "W = 60 s", "W = 300 s"],
        series: [{ name: "τ within round", slot: 2, values: [1.0, 0.004, 0.0013, 0.0018, 0.0067, 0.0043] }],
        unit: "", yMin: 0, yMax: 1,
        metric_ids: ["S-TAU-WITHIN-CONVENTIONAL", "S-TAU-WITHIN-W300"], runs: ["seed/oracle"]
      },
      {
        id: "session_matrix", kind: "matrix",
        title: "Session-security attack matrix",
        note: "Each attack must be rejected for the right reason — a rejection with the wrong reason is still a bug.",
        rows: [
          { name: "Valid token + fresh DPoP proof", expected: "200", observed: "200", ok: true, why: "—" },
          { name: "Replayed proof (same jti)", expected: "401", observed: "401", ok: true, why: "jti_fresh" },
          { name: "Stolen token, attacker's own key", expected: "401", observed: "401", ok: true, why: "key_binding" },
          { name: "Proof for a different URL", expected: "401", observed: "401", ok: true, why: "htu" },
          { name: "Proof for a different method", expected: "401", observed: "401", ok: true, why: "htm" },
          { name: "Stale proof (iat −5 min)", expected: "401", observed: "401", ok: true, why: "iat_window" },
          { name: "Expired access token", expected: "401", observed: "401", ok: true, why: "token_exp" },
          { name: "Tampered access token", expected: "401", observed: "401", ok: true, why: "token_mac" },
          { name: "Refresh-token rotation", expected: "rotated", observed: "rotated", ok: true, why: "—" },
          { name: "Old refresh token reused", expected: "family revoked", observed: "family revoked", ok: true, why: "reuse detected" },
          { name: "Rotated token after reuse", expected: "family revoked", observed: "family revoked", ok: true, why: "reuse detected" },
          { name: "X25519 + HKDF content key", expected: "keys equal", observed: "keys equal", ok: true, why: "—" }
        ],
        metric_ids: ["SEC-E5-PASS"], runs: ["seed/oracle"]
      },
      {
        id: "kernel_sweep", kind: "lineLog", pending: true,
        title: "Bitonic permute: GPU vs CPU",
        note: "Kernel time against slot count, log–log, with the crossover marked.",
        how: "M07 · pack the kernel sweep job, run it on the free runner, then ingest the result bundle",
        metric_ids: ["K-BITONIC-FUSED-MS-2^n", "CPU-BITONIC-MS-2^n", "X-CROSSOVER-N"]
      },
      {
        id: "pipeline_breakdown", kind: "stackedBar", pending: true,
        title: "One epoch, stage by stage",
        note: "H2D, tags, sort, compaction, D2H and seal against the 200 ms epoch budget.",
        how: "M07 · pipeline job at 2^6 … 2^16 slots",
        metric_ids: ["P-WRITE-EPOCH-P99-S65536"]
      },
      {
        id: "e2e_latency", kind: "lineLog", pending: true,
        title: "End-to-end latency vs the unprotected baseline",
        note: "What privacy costs a user, at 10, 100 and 1000 simulated users.",
        how: "M15 · needs the service (M10) and session layer (M11) running",
        metric_ids: ["E2E-P99-U100-VCLOAK", "E2E-P99-U100-BASELINE"]
      }
    ],

    missing: [
      { metric_id: "K-BITONIC-FUSED-MS-2^16", how: "M07 — kernel sweep on the GPU runner" },
      { metric_id: "X-CROSSOVER-N", how: "M07 — GPU and CPU baselines in one runner session" },
      { metric_id: "T-DUDECT-MAXT-BITONIC", how: "M08 — dudect at N = 10^5 per class" },
      { metric_id: "T-NCU-BRANCHEFF-BITONIC", how: "M08 — Nsight Compute on the runner" },
      { metric_id: "E2E-P99-U1000-VCLOAK", how: "M15 — load generator against the live service" }
    ]
  },

  /* Rows as the database would hold them: physical order ≠ send order. */
  dump: {
    mode: "vcloak", window: 41,
    rows: [
      { row_id: "9f3c1a7e-5d02-4b19-8c77-2e1a4f6b0d93", bucket: 23, win: 41, seq_enc: "7a1f…c4e2", payload: "b91d…0f7a", sent: 4 },
      { row_id: "1c8d4b2f-9e71-4a30-bb16-7f0c3d9a5e24", bucket: 23, win: 41, seq_enc: "2e94…81bd", payload: "4cfa…66e1", sent: 1 },
      { row_id: "ae57062b-3c84-4f6d-9a21-0b5e8c7d1f49", bucket: 51, win: 41, seq_enc: "c033…97aa", payload: "7e20…b3c8", sent: 6 },
      { row_id: "63b9e0d4-7a15-42c8-8e53-9d2f1b6a4c07", bucket: 23, win: 41, seq_enc: "5db7…1e60", payload: "a048…2d95", sent: 3 },
      { row_id: "f204a8c6-1b93-4e57-a7d0-6c8b2e4f9031", bucket: 51, win: 41, seq_enc: "9f61…4c72", payload: "15bc…e807", sent: 5 },
      { row_id: "7d1e9352-4f08-4ba6-91c4-3a7d05e2b8f6", bucket: 23, win: 41, seq_enc: "e8a2…57d1", payload: "cc39…401f", sent: 2 },
      { row_id: "2a6f8b14-0d75-49e3-82af-5e1c9d0b3a7e", bucket: 12, win: 41, seq_enc: "31c5…0b9e", payload: "78da…93b2", sent: 7 },
      { row_id: "b5c37f90-6e2a-41d8-94b7-0f3e8a1c6d52", bucket: 23, win: 41, seq_enc: "ab47…ee30", payload: "0e65…1a4d", sent: 8 }
    ]
  },

  logs: {
    session: [
      "# SESSION LOG (append-only; newest at the bottom)",
      "",
      "## Session 1 — 2026-10-11 09:14 — M00 Bootstrap & GPU runner — owner:Aditya",
      "- Steps: S1→S5 (status after: IN_PROGRESS)",
      "- Did: venv + requirements.lock; package skeleton; runtime backend selection (numpy|cupy);",
      "        telemetry with NVML no-op fallback; scripts/gpujob.py pack|ingest|verify",
      "- Evidence: runs/20261011-091402_M00_bridge_selftest, tests/unit (14/14)",
      "- Metrics added: none yet (probe job not yet run)",
      "- Decisions: none (ADR-009..011 already recorded in the kit)",
      "- Issues: opened ISSUE-1 (GPU JOB READY — job M00-probe-a31f)",
      "- Deviations from spec: none",
      "- Commit: 4c1e9a2",
      "- Next: M00 S6 ; human action: ISSUE-1 — upload gpujobs/out/M00-probe-a31f/job.zip",
      "",
      "## Session 2 — 2026-10-11 10:02 — M00 Bootstrap & GPU runner — owner:Aditya",
      "- Steps: S6→S7 (status after: AUDIT_PENDING)",
      "- Did: ingested results_M00-probe-a31f.zip; verified bundle sha + git sha; filled STATE.runner",
      "- Evidence: runs/20261011-095533_M00_probe (Tesla T4, driver 550.54, CUDA 12.4, CuPy 13.3)",
      "- Metrics added: ENV-PEAK-BW, ENV-D2D-BW, ENV-MAX-LOG2N, ENV-VRAM-FREE",
      "- Issues: closed ISSUE-1",
      "- Commit: 7b20d4f",
      "- Next: M00 audit ; human action: none"
    ],
    audit: [
      "# AUDIT LOG",
      "",
      "## Audit M00 — 2026-10-11 — session 3 — result: PASS",
      "| Item | Result | Evidence |",
      "|---|---|---|",
      "| A1 pytest passes with no GPU present | PASS | runs/…_M00_audit/pytest.txt (14/14) |",
      "| A2 pack→ingest round trip; tampered bundle rejected | PASS | runs/…_M00_bridge_selftest/ |",
      "| A3 Ingested probe shows a real NVIDIA GPU | PASS | runs/…_M00_probe/result.json (Tesla T4) |",
      "| A4 Measured D2D ≤ theoretical peak | PASS | 213.4 ≤ 320.0 GB/s |",
      "| A5 numpy-backend perf metric is rejected | PASS | runs/…_M00_audit/check_metrics.txt |",
      "| G1 Tests pass in a fresh process | PASS | runs/…_M00_audit/pytest.txt |",
      "| G2 No fabricated numbers | PASS | check_metrics.py clean |",
      "| G2b GPU provenance | PASS | manifest backend=cupy, runner=colab |",
      "| G4 Secrets hygiene | PASS | check_secrets.py clean |",
      "| G7 Git hygiene | PASS | 7b20d4f, owner tag present |",
      "| G10 Reproducibility | PASS | manifest has git_sha, seed, command, env |",
      "Notes: ncu counters permitted on the runner; recorded for M08."
    ],
    metrics: [
      "| Metric ID | Value | Unit | Stat | Module | Run dir | Date | Quick | Backend | Runner |",
      "|---|---|---|---|---|---|---|---|---|---|",
      "| ENV-PEAK-BW | 320.0 | GB/s | theoretical | M00 | runs/20261011-095533_M00_probe | 2026-10-11 | no | cupy | colab |",
      "| ENV-D2D-BW | 213.4 | GB/s | median | M00 | runs/20261011-095533_M00_probe | 2026-10-11 | no | cupy | colab |",
      "| ENV-MAX-LOG2N | 24 | log2(slots) | derived | M00 | runs/20261011-095533_M00_probe | 2026-10-11 | no | cupy | colab |",
      "| ENV-VRAM-FREE | 14.7 | GB | snapshot | M00 | runs/20261011-095533_M00_probe | 2026-10-11 | no | cupy | colab |"
    ],
    issues: [
      "# ISSUES",
      "",
      "### ISSUE-1 [CLOSED 7b20d4f] GPU JOB READY — M00-probe-a31f",
      "BLOCKS: M00   SEVERITY: medium   OPENED: 2026-10-11 session 1",
      "Why: the device probe needs a real NVIDIA GPU; this laptop has none.",
      "Do this:",
      "  1. Open colab/VCloak_GPU_Runner.ipynb in Google Colab.",
      "  2. Runtime → Change runtime type → T4 GPU.",
      "  3. Run Cell 1, upload gpujobs/out/M00-probe-a31f/job.zip at Cell 2, run Cells 3–4.",
      "  4. Put results_M00-probe-a31f.zip into gpujobs/inbox/.",
      "Confirm by running: ls gpujobs/inbox/",
      "Then type: continue"
    ]
  },

  leak: [
    ["Message content", "no", "AES-256-GCM under a key only the two clients hold"],
    ["Message length", "no", "every message is padded to a fixed block"],
    ["Order within a window", "no", "GPU permutation, re-shuffled when the window closes"],
    ["Primary key / arrival rank", "no", "random UUID instead of an auto-increment id"],
    ["Ordering key", "no", "lives in GPU memory; never written to disk"],
    ["Conversation identity", "partial", "many conversations share one bucket"],
    ["Order across windows", "yes", "the window id is coarse but visible"],
    ["Real messages per window", "yes", "dummies are stripped before the rows are written"],
    ["Order of the newest data", "yes", "epoch-level, until that window closes"]
  ]
};
