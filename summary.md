# V-cloak — project summary

Status on 2026-10-13, after build session 40. Every number here is copied from `state/METRICS_INDEX.md`
or a run folder under `runs/`; the metric id or run folder is given beside it.

---

## 1. What we are doing

V-cloak is a capstone project (SCOPE, VIT Chennai; guide Dr. Mary Shamala L.). It is a layer for a
messaging backend that **hides the order in which encrypted messages were stored**.

**The problem.** In a normal chat backend the messages are encrypted, but the database still stores them
in arrival order. Someone who steals a copy of the database (a backup, a `pg_dump`, a disk image) cannot
read the messages, but can see who answered whom and when, just from the row order.

**Our idea.** Before a batch of messages is written to the database, it is shuffled inside GPU memory with
a secret key that never leaves the GPU. The database only ever receives the shuffled rows. The true order
is kept as an encrypted sequence number that only the GPU can open, so the real recipient still gets the
conversation in the right order.

## 2. Our goal

Three properties, which the whole evaluation is built around:

| | Property | Meaning |
|---|---|---|
| P1 | Order is hidden inside a window | A stolen dump does not show the order of messages inside one time window (default 60 s) |
| P2 | Correct restoration | The authorised reader still gets every conversation in the true order |
| P3 | Data-oblivious execution | What the GPU kernels touch, and how long they take, depends only on public sizes, not on the content or the order |

**What we do not claim.** The attacker is passive and only has a copy of the stored data. A hacked
*running* server, GPU memory dumps and network traffic analysis are out of scope. The window a message
belongs to, the number of messages per window and a partial hint of the conversation (the bucket) stay
visible. These limits are written down on purpose and must stay in the report.

## 3. How it works

```
[Client A/B] --TLS + DPoP--> [Session gateway] --> [Round scheduler] --> [GPU engine] --> [PostgreSQL]
                                  |                                  ^   (keys in VRAM)      |
                                  +--> [Read handler] --fixed-K fetch+----------------------+
```

**Writing a message**
1. The client pads the message to a fixed size and encrypts it with a key only the two users have.
2. The server collects messages for 200 ms (one *epoch*) and pads the batch with dummy rows to a fixed size.
3. The GPU gives every row a random 128-bit tag (ChaCha20 under a key held in GPU memory) and sorts the rows
   by tag with a bitonic sort. Sorting by random tags is the shuffle.
4. The dummies are removed without revealing where they were, and the shuffled rows go to PostgreSQL.
5. When a 60 s window closes, the whole window is shuffled once more.

**Reading a conversation**
1. The server fetches a fixed-size set of candidate rows for a (bucket, window).
2. The GPU opens the encrypted sequence numbers and sorts the rows back into the true order.
3. The client decrypts the messages.

The bitonic sort is used because it compares the same pairs of positions whatever the data is, which is
what "oblivious" means here.

## 4. Tech stack

| Area | What we use |
|---|---|
| Language | Python 3 (3.14 on the laptop), CUDA C for the kernels (`kernels/*.cu`) |
| GPU | CuPy (raw CUDA kernels), NVML telemetry, CUDA events for timing; Tesla T4 on free Colab / Kaggle |
| CPU stand-in | A NumPy backend that runs the same kernel logic on a laptop with no GPU (correctness only) |
| Cryptography | ChaCha20, ChaCha20-Poly1305 and a ChaCha20 PRF on the GPU; AES-256-GCM, X25519, HKDF-SHA256 on the client; Argon2id to unseal the master key (`cryptography`, `argon2-cffi`) |
| Backend | FastAPI + Uvicorn, WebSockets, DPoP session tokens with refresh rotation |
| Database | PostgreSQL (16 in Docker, 16 on the runner) through `psycopg`; SQLite for quick development |
| Frontend | Plain HTML, CSS and JavaScript in `web/` (chat, dashboard, experiments, logs, architecture views), served by the backend |
| Evaluation | NumPy, SciPy, pandas, matplotlib |
| Quality | pytest (2114 tests pass locally, 675 skip: 674 of those need a GPU and passed on the T4), ruff, our own checks for fabricated numbers, secrets and oblivious code |
| Tooling | Git, Docker Compose, `setup/bootstrap.ps1` / `bootstrap.sh`, a Colab notebook that runs packed GPU jobs |

## 5. How we build and run it

**How the build is organised.** The project is split into 23 work units (M00 to M22). One session does one
unit: code, tests, measurements, an audit, then a commit tagged with the owner. Progress lives in `state/`
(`STATE.md`, `SESSION_LOG.md`, `AUDIT_LOG.md`, `ISSUES.md`, `METRICS_INDEX.md`). 40 sessions so far.

**No GPU on our laptops.** GPU work is done as a job: the session packs `gpujobs/out/<job>/job.zip`, one of
us uploads it to Colab or Kaggle with `colab/VCloak_GPU_Runner.ipynb`, downloads the results zip into
`gpujobs/inbox/`, and the next session checks and ingests it. A number is only called a GPU result if it
came back this way.

**Rule we hold ourselves to.** No number is typed by hand. Every figure, table and dashboard value must
trace to a run folder. If something could not be measured it is written as `NOT_MEASURED` with the reason.

**Running it locally**

| To do this | Run |
|---|---|
| Set up the project | `setup/bootstrap.ps1` (Windows) or `setup/bootstrap.sh` |
| Start the database | `docker compose up -d --wait db` |
| Start the server (development) | `python -m vcloak.cli serve --dev --store sqlite` |
| Two-user demo from the terminal | `python scripts/demo_two_users.py` |
| Run the tests | `pytest -q` (GPU tests skip without a GPU) |
| Security evaluation | `python bench/run_security_eval.py --stage s1\|attack\|uniformity\|trace\|anonymity` |

## 6. Can it run on someone else's device?

**Yes, with two levels.**

- **Any laptop, no GPU needed.** Clone the repository, run the bootstrap script, start the server. The
  NumPy backend does the same shuffling logic on the CPU, so the chat, the storage, the read path and the
  tests all work. This shows that the system is *correct*, but it gives **no** security or speed evidence
  about a GPU.
- **The real path needs an NVIDIA GPU with CUDA.** It has only been run on a Tesla T4 on Colab and Kaggle.
  It has not been tried on any other card.
- **An integrated (laptop) GPU cannot be used**, and that is a security reason, not a convenience one: it
  shares memory with the CPU, so "the key lives only in GPU memory" would not be true.
- It is **not deployed anywhere**. There is no public server. `--dev` mode uses a public development key
  and only listens on the local machine; it is for demos, never for real messages.

## 7. What kind of thing is it?

It is a **research prototype**: a working proof-of-concept system with an evaluation behind it.

- It is **not an AI/ML model**. Nothing is trained. It is systems and security engineering: cryptography,
  GPU kernels, a backend, a database and a web client.
- It is **not a finished product**. It has no deployment, no user accounts at scale and no independent
  security review, and session state is kept in memory.
- What it is good for: demonstrating the idea end to end, measuring how well it hides order, measuring
  what it costs, and supporting the report and a paper.

## 8. What is done (15 of 23 units done, 1 in progress)

Owners: **Aditya** GPU kernels and profiling · **Divyansh** backend, storage, sessions · **Abhishek**
crypto, client, evaluation.

| Unit | Owner | What it did |
|---|---|---|
| M00 Bootstrap and GPU probe | Aditya | Project set up so it runs on a laptop without a GPU; the free T4 runner checked; the pack → upload → ingest loop working |
| M01 Oracle and golden vectors | Abhishek | The original CPU reference script turned into a tested package with fixed test vectors; it is the ground truth for the GPU tests |
| M02 CPU crypto and keys | Abhishek | Byte-exact CPU versions of every server-side crypto function, the client encryption, and sealing/unsealing of the master key |
| M03 GPU bitonic sort | Aditya | The core CUDA sort, with no data-dependent branch or memory address, equal to the reference bit for bit |
| M04 GPU ChaCha20 | Aditya | Tags, subkey derivation and the bucket function on the GPU, keys read from GPU memory only |
| M05 GPU read path | Aditya | Opening the encrypted sequence numbers on the GPU, the restore sort, and removing dummies obliviously |
| M06 GPU engine | Aditya | One `GpuEngine` API (`write_epoch`, `read_window`, `reshuffle`): the only server part that touches keys |
| M07 GPU performance | Aditya | Kernel and pipeline timings, CPU baselines, GPU/CPU crossover, telemetry. Many configurations were unstable on the shared T4 (ISSUE-15) |
| M08 Obliviousness audit | Aditya | Timing-leak tests (dudect) and a reading of the compiled code. **Negative result kept:** some series fail; they were traced to the test harness and to host Python, not the kernels. We never say "constant time" |
| M09 Storage | Divyansh | PostgreSQL schema that stores no arrival information, split by window, with atomic rewrite of closed windows |
| M10 Service | Divyansh | The running backend: 200 ms epoch scheduler, read handler, and an unprotected *baseline* mode for comparison |
| M11 Session security | Divyansh | DPoP proofs, refresh-token rotation, WebSocket tickets, log redaction, checked with an attack matrix |
| M12 Client and CLI | Abhishek | Python client doing key agreement, padding, encryption, send and read; scripted two-user demo |
| M13 Frontend, part 1 | Abhishek | Live two-user chat in the browser that also shows what the server stores, with a V-cloak / baseline switch |
| M14 Security evaluation | Abhishek | **In progress**, see below |

### M14 so far (measured on the real stack: Tesla T4 + PostgreSQL, 24733 messages, one seed)

How often an attacker with the dump guesses the order of two consecutive messages of a conversation
(50% is a coin flip):

| Storage layout | Turn-order accuracy | Metric |
|---|---|---|
| Unprotected baseline | 100% | `S-TURNACC-BASELINE` |
| V-cloak, shuffle per 200 ms epoch only | 98.2% | `S-TURNACC-EPOCH` |
| V-cloak, window 1 s | 92.0% | `S-TURNACC-W1` |
| V-cloak, window 10 s | 68.7% | `S-TURNACC-W10` |
| V-cloak, window 60 s (default) | 55.6% | `S-TURNACC-W60` |
| V-cloak, window 300 s | 50.7% | `S-TURNACC-W300` |

- **Restoration:** 60 of 60 conversations read back in exact order (`S-E0-RESTORE`).
- **Uniform shuffle:** chi-square p-value 0.90 (`S-CHI2-P`); 99.7% of epochs inside the expected band
  (`S-TAUBAND-PCT`). Both gates pass.
- **Comparator trace:** 1 distinct trace on the GPU sort against 4 for a merge sort over the same inputs
  (`S-TRACE-DISTINCT-DEVICE`, `S-TRACE-DISTINCT-MERGESORT`).
- **Against the CPU oracle:** 31 of 35 rows agree, 2 are defined differently, 2 differ on the oracle's
  side (ISSUE-41). We do not write "the GPU matches the oracle".
- 674 of 674 GPU-only tests passed on the T4 (`S-CUDA-TESTS-PASSED`).

## 9. What is left

| Unit | What we have to do in it |
|---|---|
| **M14 S6** (now) | Anonymity set: how many real messages share a window at 10, 100 and 1000 users. The code is written and GPU job `20261013-125843_M14_s6` is packed. **Waiting for one of us to run it on Colab** (ISSUE-42), then ingest and close M14 |
| M15 End-to-end performance | Latency and throughput of V-cloak against the unprotected baseline at 10, 100 and 1000 users, with GPU load sampled. Needs ISSUE-12 fixed first |
| M16 Results export | Turn the indexed metrics into paper-ready tables, figures and macros with no manual copying |
| M18 Frontend, part 2 | Dashboard, experiments and live logs showing every measured result, generated from the evidence |
| M17 Final audit and demo | Prove the project rebuilds from a clean clone, re-run every audit, script the Review demo |
| M22 Draft report | Preliminary pages, Chapters 1 to 4, citations and the similarity check |
| M19 Publication / IP | Submit a paper or file IP and archive the proof. Calendar-bound, so it should start as soon as M16 has results |
| M20 Final report | Interpretation of results, refinements, limitations |
| M21 Review-4 readiness | Show it runs as one system, every panel comment answered, each member able to demo their own part |

## 10. Known problems we must be honest about

- **Speed at large batches (ISSUE-12).** With 65536 slots per epoch the write misses the 200 ms budget.
  The cause is host Python work, not the GPU. It blocks M15.
- **Timing side channel (M08).** Leakage tests fail for some whole-call measurements. P3 is claimed for
  the GPU kernels only; host timing is a stated limitation.
- **Profiler counters not available** on the free runner, so that check is `NOT_MEASURED` (ISSUE-18); the
  compiled-code claim rests on a manual reading (ISSUE-19).
- **Window 300 s** fills a bucket beyond the read limit `CAND_K`, so it is only used for the ablation.
- **One GPU model, one seed** for most security numbers.
- Open decisions for us: ISSUE-36, ISSUE-41, ISSUE-42.

## 11. Where to look

| For | Open |
|---|---|
| Where the build stands | `state/STATE.md` |
| What each session did | `state/SESSION_LOG.md` |
| Every measured number | `state/METRICS_INDEX.md`, `runs/` |
| Open problems | `state/ISSUES.md` |
| Design and threat model | `ai/PROJECT_BRIEF.md`, `ai/ARCHITECTURE.md`, `ai/DECISIONS.md` |
| What needs a human | `YOUR_CHECKLIST.md` |
| Screenshots and figures | `evidence/`, `results/` |
