# YOUR CHECKLIST — everything that needs a human, in one page

Claude does the building. This is the short list of things it cannot do for you, in the order you'll hit them.
Nothing here takes more than a few minutes except the two marked ⏳, which depend on other people.

**You don't need to prepare any of this in advance.** When a step needs you, the session stops and prints the
exact instructions — paths, links, menu clicks — right there in the IDE, and the same text goes into
`state/ISSUES.md`. This page is just so you know what's coming. The only thing worth doing early is making a
Google account if you don't have one, because the first GPU job arrives in session 1 or 2.

---

## Once, at the start

| # | What | How long | Notes |
|---|---|---|---|
| 1 | Install **Claude Code**, open the `vcloak` folder, type `continue` | 10 min | The agent then runs `setup/bootstrap` itself: Python, Git, venv, packages, git identity |
| 2 | Have a **Google account** (Colab) or a **Kaggle account** | 2 min | Kaggle needs a one-time phone verification before it gives you a GPU |
| 3 | Tell the agent your **name and email** when it asks, once | 10 s | This is what makes commits attributable to you — each teammate does this on their own machine |

---

## Every GPU job (about 2 minutes, roughly 8 times across the project)

When a session ends with **`GPU JOB READY`**, you do this. Nothing else in the project is blocked meanwhile.

### On Google Colab (default — use for most jobs)
1. Go to **colab.research.google.com** → `File` → `Upload notebook` → pick `colab/VCloak_GPU_Runner.ipynb`.
2. **`Runtime` → `Change runtime type` → Hardware accelerator: `T4 GPU` → `Save`.** ← the step everyone forgets
3. Run **Cell 1**. It must print a GPU name (e.g. `Tesla T4`). If it says `NO GPU`, redo step 2.
4. Run **Cell 2**, and when the file picker appears choose `gpujobs/out/<job-id>/job.zip` from your repo.
5. Run **Cell 3** and leave the tab open and visible. Short jobs take ~2 min; the big sweeps ~20–40 min.
   Colab stops notebooks it thinks you've abandoned, so don't close the laptop mid-run.
6. Run **Cell 4** → `results_<job-id>.zip` downloads.
7. Move that file into `gpujobs/inbox/` in your repo. New Claude Code session → type `continue`.

### On Kaggle (use for the long jobs: M07 sweep, M08 dudect)
1. **kaggle.com** → `Create` → `New Notebook` → `File` → `Import Notebook` → upload the same `.ipynb`.
2. Right panel → `Settings` → `Accelerator` → **`GPU T4 x2`** (verify your phone once if asked).
3. Kaggle has no file-upload box inside the notebook. Instead: right panel → `+ Add Input` → `Upload` →
   upload `job.zip` as a dataset. Kaggle unpacks the zip into a folder; that is expected. You do not type a
   path: **Cell 2** finds the job under `/kaggle/input` by itself and checks that the files are what was packed.
   (If you re-use an old notebook, re-import the `.ipynb` first so that you have the current Cell 2.)
4. Run all cells. The results zip appears in the **Output** panel on the right — download it from there.
5. Same as Colab: drop it into `gpujobs/inbox/`, then `continue`.

**Which to pick:** Colab for anything under ~15 minutes, Kaggle when the agent says the job is long or when
Colab refuses you a GPU (free GPUs are rationed; it usually clears within an hour).

### What to bring back — and that's all
Just the `results_<job-id>.zip`. Everything else — the GPU name, driver, CUDA version, timings, telemetry —
is already inside it, and the agent verifies the bundle's checksum and the commit it was packed from before
trusting a single number. You never retype a result.

**Nice to have:** a phone photo or screenshot of Cell 1 showing the GPU name, the first time you run a job.
It's a 5-second capture that becomes a figure in the paper's setup section.

---

## When the agent asks (a sentence each, not a task)

| Trigger | What it needs from you |
|---|---|
| `HUMAN ACTION REQUIRED` in the handoff | Read `state/ISSUES.md` — it has the exact steps |
| Around M09 | **Docker Desktop** installed, for PostgreSQL |
| M06/M10 | A passphrase for the dev key, or just say "use the dev key" |
| Any ambiguous design call | A one-line answer; it won't guess on things that can't be undone |

---

## ⏳ The two that depend on other people — start them early

### A. Similarity check (Draft Review, 1 mark)
- The agent produces the submission-ready PDF. **You** get it run through the institute's tool
  (Turnitin / Urkund / whatever SCOPE prescribes) — usually via your guide or the department.
- Put the report file into `review/similarity/`.
- **Ask a week before the deadline.** There is a queue, and the agent will never state a score it
  didn't receive from the real tool.

### B. Paper submission (Review 4, 2 marks — zero without proof)
- The agent writes the paper and shortlists venues with verified deadlines. **You** press submit.
- Then save three things into `review/publication/submission_proof/`:
  1. the confirmation email, saved as PDF,
  2. the submission / paper ID,
  3. a screenshot of the portal showing the submitted state.
- A finished manuscript that was never submitted scores **nothing** on this criterion. It's the only
  item in the project with a hard external deadline, so M19 starts as soon as there are real results.

---

## After each review

**Paste the panel's comments into `state/REVIEW_FEEDBACK.md`, word for word — including the vague ones.**

Review 4 criterion 1 (2 marks) is scored purely on evidence that earlier comments were acted on. The agent
is forbidden from inventing a comment it wasn't given, so an empty file genuinely costs you those marks.
Same for anything your guide says on a read-through.

---

## What you never have to do

Write code · install CUDA or CuPy · run tests · make charts · take dashboard screenshots · copy numbers
into the report · keep the logs · remember where you left off.

Type `status` to see where things stand, or `review check` for an honest scorecard against the rubric.
