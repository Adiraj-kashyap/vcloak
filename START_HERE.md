# START HERE — V-cloak autonomous build kit

> **In a hurry?** `YOUR_CHECKLIST.md` is the one-page list of everything that needs *you*,
> including exactly what to click on Colab and Kaggle and what to bring back.

This folder builds V-cloak for you. Open it in **Claude Code** and type `continue`. Claude does one
piece of the project, tests it, audits it, writes the logs, commits, and stops. You open a new
session, type `continue`, and it carries on from exactly where it left off.

**You do not need a GPU in your laptop.** The CUDA work runs on a free cloud GPU; see §3.

---

## 1. What you get

- A working **messaging app** (`web/`) with five views: Chat, Dashboard, Experiments, Logs, Architecture.
  A prototype is already in this kit — open `web/index.html` in a browser right now and click around.
- A **GPU-resident oblivious permutation** in CUDA, verified byte-for-byte against a CPU reference.
- **Evidence for every claim**: each measurement lands in `runs/` with a manifest, is indexed in
  `state/METRICS_INDEX.md`, and is rendered on the dashboard with the run folder it came from.
- A build that is **attributable**: each module has an owner and every commit is tagged with it.

---

## 2. Folder structure (keep it exactly like this)

```
vcloak/                        ← open THIS folder in Claude Code
├── CLAUDE.md                  ← loaded automatically every session: the rules + session loop
├── START_HERE.md              ← this file (for humans)
├── YOUR_CHECKLIST.md          ← one page: every task that needs a human, in order
├── .claude/
│   ├── settings.json          ← pre-approved safe commands (fewer permission prompts)
│   └── skills/                ← /continue · /status · /audit · gpu-job · gpu-bench · session-close
├── ai/                        ← the specifications (Claude reads these on demand)
│   ├── PROTOCOL.md  PROJECT_BRIEF.md  ARCHITECTURE.md  CONVENTIONS.md
│   ├── GPU_RUNNER.md          ← no local GPU: the free Colab/Kaggle workflow
│   ├── GPU_GUIDE.md  FRONTEND.md  SKILLS_MATRIX.md
│   ├── LOGGING_AND_AUDIT.md  TESTING.md  DECISIONS.md
│   └── modules/M00 … M18      ← one file per work unit
├── state/                     ← the memory between sessions (Claude maintains these)
│   ├── STATE.md               ← where we are, what's next
│   ├── SESSION_LOG.md  AUDIT_LOG.md  ISSUES.md  METRICS_INDEX.md
├── web/                       ← the frontend prototype (chat + dashboard + logs)
├── setup/                     ← bootstrap.ps1 / bootstrap.sh (the agent runs this for you)
├── colab/                     ← VCloak_GPU_Runner.ipynb + gpu_entry.py
├── gpujobs/                   ← out/ · inbox/ · done/  (the GPU bridge — see its README)
├── review/                    ← rubric scorecard, demo script, Q&A bank, publication proof
└── seed/                      ← the CPU reference oracle + the paper's results contract
```
Claude creates everything else (`src/`, `kernels/`, `tests/`, `bench/`, `runs/`, `results/`, `docs/`).
Don't rename or move kit files, and don't hand-edit `state/` unless an issue asks you to.

---

## 3. The GPU question (read this once)

**Your laptop's integrated GPU cannot be used, and that is a security fact, not a limitation of effort.**
An integrated GPU shares system RAM with the CPU. V-cloak's whole claim is that the ordering key lives
in GPU memory that a host-level dump never sees — on an iGPU that separation does not exist. It also has
no CUDA. Both reasons are recorded as ADR-010; say this if the panel asks.

So the project uses a **free cloud GPU**:

| | Google Colab | Kaggle Notebooks |
|---|---|---|
| GPU | usually a T4 (16 GB) | T4 ×2 or P100 |
| Good for | quick kernel runs | long sweeps, dudect |
| Session | up to 12 h, idle timeout | up to 12 h |
| Cost | free | free (phone-verify once to unlock the GPU) |

**How it works in practice.** Claude writes the kernels and tests them locally against a NumPy
"thread-model" twin that reproduces the same kernel logic. When it needs real GPU numbers it packs a
job and stops. You spend about two minutes:

1. Open `colab/VCloak_GPU_Runner.ipynb` in Colab (File → Upload notebook).
2. `Runtime → Change runtime type → T4 GPU`.
3. Run the cells; upload `gpujobs/out/<job-id>/job.zip` when asked.
4. Put the downloaded `results_<job-id>.zip` into `gpujobs/inbox/`.
5. New session → `continue`. Claude verifies and ingests it.

Claude verifies the bundle checksum and the commit it was packed from, so numbers cannot drift or be
retyped. A figure measured under the local NumPy backend is **rejected** as a performance result by rule.

---

## 4. One-time setup

**You do two things. Claude does the rest.**

1. **Install Claude Code** — desktop app, VS Code extension, or `npm i -g @anthropic-ai/claude-code`.
   Sign in, then open this `vcloak` folder in it.
2. **Have a Google account** (for Colab) **or a Kaggle account**. You almost certainly have the first.
   Kaggle needs a one-time phone verification before it will give you a GPU — do it now if you prefer Kaggle.

Then open the folder in Claude Code and type `continue`. In its first session the agent runs
`setup/bootstrap.ps1` (Windows) or `setup/bootstrap.sh` (macOS/Linux) for you, which:

- installs Python and Git if they are missing (via winget / brew / apt),
- creates the `.venv` virtual environment and installs the Python packages,
- starts the git repository,
- asks once for your name and email, and sets them for this folder so commits are attributed to you.

You can also run that script yourself first if you'd rather watch it happen:
`powershell -ExecutionPolicy Bypass -File setup\bootstrap.ps1`  ·  `bash setup/bootstrap.sh`

Two notes:
- If the script installs Python or Git, Windows needs a **new terminal** before they appear on PATH.
  The script says so and exits cleanly; run it again (or type `continue` again) and it carries on.
- **Each teammate runs it once on their own machine, with their own name.** That is what makes the
  contributions slide match the git history, and it is the only reason the script asks who you are.

**Docker** is needed only from M09 onward (PostgreSQL). The agent will tell you when, and nothing
before that is blocked on it. Nothing at all needs installing for the GPU — Colab and Kaggle already
have CUDA, nvcc, Nsight and CuPy.

## 5. Daily use

| You type | What happens |
|---|---|
| `continue` | Does the next unit, then stops with a short handoff |
| `continue M07` | Works on M07 specifically (if its dependencies are done) |
| `continue quick` | Same, with small measurement sizes — quick numbers never become final results |
| `status` | Progress table, open issues, latest metrics. Changes nothing |
| `audit M05` | Re-checks a finished module |
| `fix ISSUE-4` | Works only on that issue |
| `review check` | Scores you against the Review 4 rubric and lists what is missing. Changes nothing |

**After each handoff, start a fresh session** (new tab, or `/clear` in the terminal) and type `continue`.
A fresh session reads only `CLAUDE.md`, `state/STATE.md` and the one current module file, which is what
keeps each session cheap.

**If the handoff says `GPU JOB READY`** → do the five steps in §3, then `continue`.
**If it says `HUMAN ACTION REQUIRED`** → open `state/ISSUES.md`, follow the steps, then `continue`.

---

## 6. The plan

| Phase | Modules | Sessions (approx.) | What exists at the end |
|---|---|---|---|
| Foundation | M00–M02 | 4 | Project, GPU bridge proven, reference oracle, crypto |
| **GPU core** | M03–M06 | 9 | CUDA kernels + engine, byte-identical to the reference |
| **GPU evidence** | M07–M08 | 6 | Performance sweeps, crossover, dudect / Nsight / SASS |
| System | M09–M12 | 6 | PostgreSQL, service, session security, two-user client |
| **Frontend** | M13, M18 | 4 | Live chat + the evidence dashboard wired to real data |
| Evaluation | M14–M15 | 4 | Security results on the real stack, end-to-end latency |
| Wrap-up | M16–M17 | 3 | Paper macros and figures, final audit, demo runbook |
| **Draft review** | M22 | 3 | Preliminary pages, Ch.1–4, citations, similarity cleared |
| **Review 4** | M19–M21 | 7 | Paper submitted with proof, final report, integration + readiness |

**Fast path for Review 3** (working modules at roughly half the scope, with real GPU evidence and a
live demo): **M00 → M08, then M13**. That is about 20 sessions, plus one GPU upload per GPU module.

**For Review 4** (25 marks) the bar changes: the full scope complete, the modules integrated and stable,
results *interpreted* rather than just shown, a near-final report, and — worth 2 marks and impossible to
rush — **a paper actually submitted, with documentary proof**. The rubric and what earns each mark are in
`ai/REVIEW_RUBRICS.md`; type `review check` at any time for an honest scorecard of what is still missing.

Between the two sits the **Draft / Report Review** (5 marks, one per criterion): the preliminary pages and
Chapters 1–4, a report that matches the built system rather than the original plan, evidence behind every
claim, clean citations **within the institute's similarity limit**, and a clear statement of who did what.
That is module M22. Two things it needs from you: the institute's report template, and the similarity check
— which usually runs through your guide or department and has a queue, so ask for it a week ahead.

Three things only you can do, so do them early:
1. **Paste the Review-3 panel comments** into `state/REVIEW_FEEDBACK.md` right after the review, verbatim.
   Criterion 1 is scored from that file, and the agent will not invent comments it was never given.
2. **Get the similarity check run** on the draft PDF (M22), and save the report into `review/similarity/`.
   The agent will never state a score it did not receive from the institute's tool.
3. **Submit the paper** when M19 has it ready, and drop the confirmation email, paper ID and portal
   screenshot into `review/publication/submission_proof/`. A finished manuscript that was never submitted
   scores zero on criterion 9.

---

## 7. Seeing the app right now

Double-click `web/index.html`. It opens with bundled demo data from the CPU reference oracle: the chat,
the shuffled server rows, the charts, the attack animation and the logs all work offline. Everything
measured is labelled `SEED DATA`; everything not yet measured says `NOT MEASURED` and names the module
that will produce it. That honesty is deliberate — and the offline mode is also your fallback if the
Wi-Fi or the backend fails during the review.

Once the backend exists (M10+), `vcloak serve --dev` serves the same page at `/app` with live data.

---

## 8. What keeps it trustworthy

- **No invented numbers.** Every figure traces to a command, a `runs/` folder and a metrics row. Things
  that cannot be measured are written down as `NOT_MEASURED` with the reason.
- **The dashboard cannot lie.** It renders generated JSON only; a number typed into the HTML fails the audit.
- **GPU provenance.** Each measurement records the GPU, the runner and the session. Numbers from two
  different cloud sessions are never merged into one figure.
- **Bit-exact verification.** Every kernel is compared byte-for-byte with its CPU reference.
- **Audits.** Each module ends with its own checklist plus 11 global checks. A failed audit blocks progress.
- **Checkpoints.** `STATE.md` is updated after every step, so an interrupted session loses at most one step.

---

## 9. Two corrections this kit already applies to your paper

1. **ADR-005 — the kernel in Listing 1 has a race.** With one thread per element, the partner thread's
   `x ^= 0` can overwrite a real swap. The kit uses one thread per compare-exchange pair, and the
   indexing was verified against the reference schedule.
2. **ADR-003 — server crypto moves to ChaCha20/Poly1305.** HKDF/HMAC/AES-GCM would have run on the CPU,
   putting the ordering key in host memory and contradicting the central claim; the ARX design also avoids
   the lookup tables that GPU cache-timing attacks exploit. Client message encryption is unchanged.

M16 writes `results/PAPER_UPDATES.md` listing every passage and slide number to update.

---

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| Claude starts reading every file | "Follow CLAUDE.md §1: read only STATE.md and the current module." |
| Claude tries to do two modules at once | "Stop at the handoff (CLAUDE.md rule 5)." |
| Colab says no GPU | `Runtime → Change runtime type → T4 GPU`, then re-run Cell 1. Free GPUs are rationed; if refused, wait an hour or use Kaggle. |
| Colab disconnected mid-job | Re-run Cells 1–3. Jobs restart cleanly; nothing is half-recorded. |
| Kaggle has no file-upload box | Add the zip as a notebook input dataset and set `KAGGLE_INPUT` in Cell 2. |
| GPU numbers look noisy | Cloud GPUs are shared. The kit records the coefficient of variation and re-runs unstable sweeps rather than hiding them. |
| The app shows "demo data" | Expected until the backend exists (M10), and whenever you open the file directly. |
| STATE looks wrong | Type `status`, then `audit Mxx`. Git history is the source of truth. |
