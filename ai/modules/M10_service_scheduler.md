# M10 — Service: FastAPI, epoch scheduler, read handler, baseline mode
owner: Divyansh · depends_on: M09 · est_sessions: 2 · human_gates: none

## Goal
A running backend: clients submit ciphertexts, the scheduler closes 200 ms epochs on wall-clock boundaries,
the engine permutes, and the repo persists. Windows are re-shuffled on close. It also provides an unprotected
**baseline mode** for M15 comparisons.

## Required reading
- `ai/ARCHITECTURE.md §1, §2, §4` · `ai/PROJECT_BRIEF.md §7` · `ai/CONVENTIONS.md §4`

## Deliverables
`src/vcloak/service/app.py`, `scheduler.py`, `models.py`, `baseline.py`, `logsafe.py` (initial),
`src/vcloak/cli.py` (`vcloak serve --mode vcloak|baseline --clock wall|sim`), `docs/API.md`,
`tests/integration/test_service.py`.

## Steps
- **S1 Models and API.** `POST /v1/messages` {payload_b64, conv_token}; `POST /v1/read` {conv_token, win} → ordered payloads;
  `GET /v1/windows` → current window id; `GET /healthz`. `conv_token` is the client's opaque handle for its conversation (M11 will
  bind it to the session). Payload size is enforced to be exactly the BLOCK ciphertext size.
- **S2 Scheduler.** An asyncio task: epochs aligned to wall-clock multiples of EPOCH_MS; each tick drains the queue up to SLOTS
  (overflow carries to the next epoch and increments a public overflow counter), calls `engine.write_epoch`, then `repo.insert_rows`.
  At window close it calls `engine.reshuffle_window` + `repo.rewrite_window` for the closed window. A `--clock sim`
  mode advances a virtual clock as fast as possible (used by M14). Check: 100 sim epochs complete, and the rows are in the DB.
  Also add `--visible-round epoch|window` (default window). `epoch` reproduces the Review-1 design for the M14 comparison only.
- **S3 Read handler.** Maps conv → bucket via `engine.bucket_of`, calls `repo.fetch_candidates(bucket, win, CAND_K)`
  then `engine.read_window`. Check: a round trip of 200 messages across 3 windows returns them in order.
- **S4 Baseline mode.** The same API and table but a BIGSERIAL id + timestamptz column, inserts in arrival order, reads with
  `ORDER BY id`. Separate schema `baseline`. Check: the round trip works; the attack on the baseline dump gives τ = 1 (quick).
- **S5 Engine lifecycle.** On startup: unseal the master (passphrase from the `VCLOAK_PASSPHRASE` env var or a prompt; `--dev` uses the test key);
  on shutdown: zeroize. Check: a shutdown test confirms zeroize was called.

## Audit checklist
- A1 Epoch boundaries are wall-clock aligned and never extended (test with an injected slow engine: overflow carries).
- A2 Window rewrite happens exactly once per closed window. A3 The baseline and V-cloak modes share the API contract (same tests).
- A4 No forbidden fields in logs (logsafe unit test). G1–G10.

## Presenter notes
1. What happens if more than SLOTS messages arrive in one epoch?
2. Why is the epoch never extended to wait for late messages?
3. How does the baseline differ from V-cloak, and why do you need it?

## Next: M11
