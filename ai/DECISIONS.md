# DECISIONS (ADR log) — append only

Format: `## ADR-<n> — <title> — <ACCEPTED|PROPOSED|SUPERSEDED by ADR-m> — <date>` then Context / Decision / Consequences.

## ADR-001 — CUDA through CuPy RawModule — ACCEPTED
Context: must run on a student laptop (Windows or Linux) with minimal build friction.
Decision: kernels are `.cu` files compiled at runtime by NVRTC via CuPy; the same files also compile with nvcc for SASS checks.
Consequences: no CMake or pybind11 build; `nvcc` is only needed for M08.

## ADR-002 — Reference oracle is the correctness ground truth — ACCEPTED
Context: GPU code must be verifiable. Decision: every GPU function has a CPU `*_ref` twin; tests are bit-exact.
Consequences: the oracle is ported and updated to the crypto profile of ADR-003 in M01/M02.

## ADR-003 — GPU-native server crypto profile (ChaCha20 / Poly1305 only) — ACCEPTED
Context: the paper's draft used HKDF, HMAC-SHA256 and AES-GCM for server-side keys. Running those on the
CPU would put K_order in host memory, contradicting "K_order lives only in GPU memory". AES T-table
implementations on GPUs are also exactly what Trident and pacSCA attack.
Decision: all server-side key use runs on the GPU with the ChaCha20 block function (as a PRF and a stream
cipher) plus Poly1305: tags, subkey derivation, bucket PRF, and ChaCha20-Poly1305 for seq_enc (formats in
ARCHITECTURE §5). Client-side content crypto stays X25519 + HKDF-SHA256 + AES-256-GCM.
Consequences: table-free, constant-time-friendly kernels. The paper text (Sec. IV, Table 3, Alg. 1)
must be updated to this profile; M16 flags it.

## ADR-004 — Coarse visible window with re-shuffle — ACCEPTED
Context: E1 on the Review-1 design showed a 98.3% turn-order leak across 200 ms epochs.
Decision: visible round = window W (default 60 s); each closed window is rewritten under a fresh permutation
into a new partition; WAL retention < W. P1 is stated per window.

## ADR-005 — One thread per compare-exchange pair — ACCEPTED
Context: the paper's Listing 1 launches one thread per element; the partner thread performs `x ^= 0` writes
on both elements, which races with the active thread and can write stale values back.
Decision: launch n/2 threads, each owning exactly one pair (i, i+j). No element is written by two threads in a launch.

## ADR-006 — Payload gather on the host — ACCEPTED
Context: gathering payloads by permutation index on the GPU makes addresses depend on the secret permutation.
Decision: the GPU permutes only 24-byte key records; payload reordering happens on the host after D2H.
Consequences: a co-resident observer of host memory could learn the permutation, but that is a live-server
compromise, which is out of scope. Documented in the leakage table.

## ADR-007 — Transient host exposure of K_master at boot — ACCEPTED
Context: the sealed master key must be unsealed with a passphrase (Argon2id KEK).
Decision: unseal on the host into a `bytearray`, copy to VRAM, derive subkeys on the GPU, overwrite the
host buffer immediately. Plaintext keys never touch disk. Documented as a boot-time exposure window.

## ADR-008 — PostgreSQL primary, SQLite for tests — ACCEPTED
Decision: production path uses PostgreSQL 16 (Docker or native) with RANGE partitioning by window.
Unit and CI tests may use SQLite through the same `Repo` protocol. Evaluation numbers (M14, M15) must come from PostgreSQL.

## ADR-009 — CUDA work runs on a free remote GPU runner — ACCEPTED — 2026-10-10
Context: the development laptop has no NVIDIA GPU. The project requires CUDA (kernels, SASS, Nsight).
Decision: kernels are developed and correctness-tested locally with the `numpy` thread-model backend, and all
CUDA execution and every performance/side-channel measurement runs on Google Colab (primary) or Kaggle
(long runs) through the zip job protocol in `ai/GPU_RUNNER.md`. Both are free.
Consequences: GPU modules take two sessions (prep → human uploads → ingest). Numbers carry `runner` and
`session_id`; results are never mixed across sessions. No code or design changes.

## ADR-010 — An integrated GPU is rejected — ACCEPTED — 2026-10-10
Context: the laptop's iGPU was considered as a local substitute.
Decision: rejected. (a) It has no CUDA, so the kernels, SASS evidence and comparisons would all change.
(b) Decisive: an iGPU shares system RAM with the CPU, so "server keys live in device memory the host
never sees" is untrue there, and the threat model collapses. A discrete GPU is a requirement of the
threat model, not a performance preference. Documented in the paper's limitations.

## ADR-011 — `numpy` thread-model backend for local development — ACCEPTED — 2026-10-10
Context: without a local GPU, iteration would stall waiting on the runner.
Decision: every kernel gets a NumPy twin in `src/vcloak/gpu/sim.py` implementing the same thread-indexed
arithmetic. It serves correctness tests only; `check_metrics.py` rejects any performance metric produced
under it. GPU-vs-simulator bit-exactness is itself an acceptance gate on the runner.

## ADR-012 — One frontend: a real chat app with an evidence dashboard — ACCEPTED — 2026-10-10
Context: V-cloak is a messaging system, and Review 3 is marked on implementation, results and clarity.
Decision: a single no-build vanilla JS + SVG frontend (`web/`) served by FastAPI, with five views: Chat
(two live users), Dashboard (metrics and charts from `results/`), Experiments (attack demo and ablation),
Logs (live session/audit/metrics logs), Architecture (data-state flow). No React, no bundler, no CDN:
it must open from `file://` with bundled demo data when the backend is down, which is also the review fallback.
Consequences: charts are hand-written SVG in `web/js/charts.js`; the palette is CVD-validated in both modes.

## ADR-013 — The dashboard reads generated evidence, never hard-coded numbers — ACCEPTED — 2026-10-10
Context: the dashboard must not become a second place where numbers can drift or be invented.
Decision: the dashboard renders `web/data/dashboard.json`, generated by `scripts/export_dashboard.py`
from `state/METRICS_INDEX.md` and `runs/**/summary.json` only. Every tile carries its METRIC-ID, run dir
and `backend`/`runner` provenance, and shows `NOT MEASURED` where a metric is absent. A number typed by
hand into the frontend is an audit failure (G2).

## ADR-014 — Storage contract details fixed in M09 — ACCEPTED — 2026-10-12
Context: PostgreSQL rejects a unique constraint on a partitioned table that leaves out the partition key, so
`row_id uuid primary key` cannot be declared on `messages`. The `Repo` protocol does not say how the re-shuffle reads
a window, or what a read does when a bucket-window holds more than K rows. The build laptop has no Docker.
Decision: (1) the primary key is `(row_id, win)`. (2) `Repo` gains `window_rows(win)` (rows of one window in physical
order), the input of `storage.reshuffle.reshuffle_window`; the four methods of ARCHITECTURE §4 are unchanged.
(3) `fetch_candidates` raises `CandidateOverflow` when a bucket-window holds more than K rows; it never truncates.
(4) `rewrite_window` refuses a row count different from the one stored (`RewriteMismatch`). (5) The development
database may be a private cluster started from an installed PostgreSQL (`scripts/pgdev.py`) instead of the compose
service; both take their settings from `vcloak.storage.pgconf.HYGIENE`.
Consequences: M10 has to handle `CandidateOverflow` (K is a capacity limit, not a soft target). ADR-008 names
PostgreSQL 16; evaluation runs (M14, M15) must record the server version they used (ISSUE-20).

## ADR-015 — Service contract details fixed in M10 — ACCEPTED — 2026-10-12
Context: `POST /v1/messages` carries `{payload_b64, conv_token}` only, while `Submission` needs a 64-bit `conv_id`
and a `seq`. The module does not say what happens to an epoch when the engine is still busy, to queued messages at
shutdown, or how an epoch-level round fits the store's `int4 win`.
Decision: (1) `conv_id` = the first 8 bytes (little-endian) of SHA-256(`"vcloak-conv-id-v1\0"` + token); the token is
16-128 characters of `A-Z a-z 0-9 _ -`. (2) The server assigns `seq` = `epoch << 24 | arrival index in the epoch`: the
order of a conversation is the order in which the server accepted its messages; no per-conversation counter is kept
and the value never repeats across restarts on a wall clock. (3) An epoch takes the arrivals before its closing
boundary, first come first, at most SLOTS; the rest waits. A boundary that passes while the engine is busy is skipped
and counted (`missed`), its arrivals go into the next epoch written; messages carried because an epoch was full are
counted in `overflow`. `write_epoch` is called for an empty epoch too. (4) The queue is bounded (16 x SLOTS by
default); beyond it, and during shutdown, a submission gets 503. Shutdown writes the queue on the next boundaries,
then zeroizes the keys. A failed epoch puts its batch back at the head of the queue. (5) One thread owns the engine
and the key store: epochs, re-shuffles and reads are serialised on it. (6) With `--visible-round epoch` the stored
round is `epoch - origin`, and on the wall clock the origin is 2026-01-01T00:00:00Z. (7) The baseline stores its rows
at once (no epoch), with the hashed conversation id in the clear.
Consequences: a client cannot choose the order of its messages (M12 may carry its own sequence inside the plaintext).
Two tokens that collide in 64 bits would share a conversation. A read waits behind the epoch being written. Windows
left open, or closed while the service was down, are not re-shuffled after a restart (ISSUE-22).

## ADR-016 — Restart: a durable list of pending windows, and an acknowledgement of the write instead of a durable queue — ACCEPTED — 2026-10-12
Context: ISSUE-22. The scheduler knew in memory only which windows it had written and not yet re-shuffled, so a
window that was open at a stop or a kill, or that closed while the service was down, kept its arrival-time layout
(P1 did not hold for it). `POST /v1/messages` answered 202 from the queue, so a kill lost accepted messages and the
client could not tell.
Decision: (1) The store has a table `pending_windows(win)`. The scheduler calls `Repo.mark_pending(win)` before it
stores the first rows of a window (window layout only); `rewrite_window` deletes the mark in the transaction of the
swap. At startup the backend reads `Repo.pending_windows()` and the scheduler treats those windows as its own: the
first epoch it writes re-shuffles every one that has closed. A mark without rows (kill between the mark and the
insert) is cleared by an empty re-shuffle. (2) The queue stays in memory. A journal of it would put the arrival
order on disk, which is what the store must never hold. Instead a submission may ask for `ack: "stored"`: the
answer (201) is sent after the epoch that carries the message is committed. 503 `not_stored` means the service
stopped before the write; 504 `ack_timeout` means the message is still queued after the time in which the queue
could have been written (at least 5 s). The default stays `ack: "queued"` (202). (3) Until M11 `vcloak serve`
refuses a `--host` that is not a loopback address unless `--allow-remote` is given.
Consequences: the mark is public (a window id; the same fact shows in the layout of the partition) and adds one
table to the schema. A window that receives rows again after its re-shuffle (a clock set back, `--clock sim`
restarted on an old store) is marked and re-shuffled again. Windows written before this change carry no mark and
are not found. With `ack: "stored"` a submission takes up to EPOCH_MS; M15 must say which acknowledgement it
measures. A retry after 504 or a broken connection can store a message twice: the client de-duplicates (M12).
Supersedes the last sentence of the consequences of ADR-015.

## ADR-017 — Sessions: a signed access token, an in-memory session state, and what a session does not bind — ACCEPTED — 2026-10-12
Context: M11 S2 leaves the access-token format open (JWS HS256 over a server secret, or an opaque token with a
server-side table) and does not say where accounts and refresh tokens live, how a logout reaches tokens already
issued, what a refresh with the wrong key does, or whether a session is tied to a conversation.
Decision: (1) The access token is a JWS, HS256, header `{"alg":"HS256","typ":"at+jwt"}`, claims `sub`, `cnf.jkt`,
`fam`, `iat`, `exp` (600 s). The MAC key is 32 random bytes made at start and held in the process only, so no
verification needs a table lookup and a restart invalidates every access token. The header is compared as a
constant, so no other `alg` is ever evaluated. (2) `fam` names the refresh family of the login. A request is also
checked against the live families (`token_revoked`), so a logout or a detected reuse ends the access tokens of that
login at once, not after their 10 minutes. (3) Refresh tokens are 32 random bytes; the table is keyed by their
SHA-256 and a spent token is kept until its expiry (7 days) so that reuse can be detected. A spent token that comes
back revokes the family. A refresh with another key than the one the family is bound to is refused and does not
spend the token or revoke the family. (4) Accounts (name, Argon2id hash string), refresh families, the jti cache
and the rate-limit counters are in memory. (5) Login is limited to 20 attempts per address per 60 s and to 5
attempts per name per 300 s without a success in between; registration to 5 per address per hour. The address is
the peer address; forwarding headers are not read. (6) A session does not bind a conversation: `conv_token` stays a
capability that the two ends derive, and the server keeps no user-to-conversation relation.
(7) A refused request names the first failed check in `error_description` and in the body.
Consequences: a restart logs every client out and loses the accounts (acceptable for the prototype and the demo;
a durable account table is a later unit and must not hold anything about conversations). The per-name limit lets
anyone lock a name out for 5 minutes at a time. Behind a reverse proxy every client shares one address until a
trusted-proxy setting exists; `public_origin` must then be set for `htu`. An authenticated user who learns another
conversation's token can fetch its ciphertexts, as before M11; the content stays protected by the client keys.
Naming the failed check tells an attacker which check stopped a forged request, which the E5 matrix needs and
RFC 9449 allows. This corrects docs/API.md of M10, which said M11 would bind `conv_token` to the session.

