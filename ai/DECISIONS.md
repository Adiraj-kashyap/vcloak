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

## ADR-018 — WebSocket: an in-band ticket with a proof, and one push for everybody — ACCEPTED — 2026-10-12
Context: M11 S5 asks for a one-time ticket (30 s, bound to jkt) required for `/v1/ws`, and for a push at epoch
cadence. It does not say how a browser, which cannot set headers on a WebSocket, presents the ticket and proves the
key, what the push carries, or where the cadence comes from.
Decision: (1) `POST /v1/auth/ws-ticket` (token and proof) returns 32 random bytes; the table is keyed by their
SHA-256 and records the key thumbprint and the login (family). (2) The socket is opened without credentials; the
first text frame is `{"ticket", "dpop"}`, the proof being a DPoP proof for `GET` on the socket URL written with
`http(s)`. Nothing secret is in a URL or a header. The nine proof checks and six ticket checks are all evaluated,
then the request is decided; a ticket is spent only by the request that is accepted, so a ticket presented with
another key stays usable by its owner (the same rule as for a refresh token, ADR-017). A reused ticket does not
revoke the login: without the key it opens nothing. (3) The push is one frame per epoch boundary,
`{"type":"tick","win":N}`, the same text for every socket. A per-conversation notification would need the server to
know which socket follows which conversation, which is the relation the system exists to hide (ADR-017 (6)).
(4) The cadence is a listener on the scheduler (`on_epoch`), called after every boundary handled, also when the
epoch was empty or its write failed; the baseline backend, which has no epochs, runs a ticker on EPOCH_MS only
while a listener is registered. (5) A socket belongs to a login: logout and refresh reuse close it at once (4001),
expiry at the next boundary. Limits: 4 sockets per login, 1024 per service, 8 unspent tickets per login, 5 s for
the first frame. A client frame after the ticket closes the socket. (6) `vcloak serve --sessions` turns the layer
on and only then may listen beyond the loopback; the default stays the open API on the loopback, which the smoke
scripts and M14 use. (7) `serve` drops the HTTP server's per-connection log lines.
Consequences: every connected client learns when the server finished each epoch write, to the precision of the
network; a sender with `ack: "stored"` learned that already. A client that wants new messages reads after a tick,
so a reading pattern that follows the ticks is uniform, and one that does not is the client's own leak (M12 must
read on a fixed schedule, not on a hunch). The tick is sent after the write, so under load it is late by the write
time. With `--sessions` on a public address the passwords travel in plain HTTP unless TLS is put in front. The
socket state is in memory like the rest of the session state (ISSUE-26).

## ADR-019 — Client: static prekeys fetched without a session, a token derived from K_content, and the order checked inside the ciphertext — ACCEPTED — 2026-10-12
Context: M12 asks for prekey upload/fetch endpoints, X25519 + HKDF to K_content, a conv_token derived client-side,
and a sequence number inside the plaintext header with a client-side continuity check. It does not say who may
fetch a prekey, how the token is derived, what the header holds, or what a retry does to the numbering (ISSUE-23).
Decision: (1) `PUT /v1/prekeys` (session) sets the one prekey of the account; `GET /v1/prekeys/{username}` takes no
session, because an authenticated fetch would give the server the relation "account A asked for B's key", which
ADR-017 (6) says it must not hold. An unknown name and an account without a prekey get the same 404. The table is in
memory with the accounts (ISSUE-26). (2) K_content is the existing derivation (ADR-003) over a transcript of both
prekeys and both account names. (3) `conv_token = base64url(HKDF-SHA256(K_content, "vcloak-conv-token-v1", 24))`:
both ends compute it, it is one-way, and it is bound into the associated data of every message. (4) The plaintext
header is `version | sender | session | number`: `sender` is the rank of the party's prekey, `session` 8 random
bytes per client start, `number` counts from 0 within the session. A reader accepts 0, 1, 2, ... per
(sender, session); an already accepted number is a repeat and is dropped, a higher one raises. (5) A message is
sent with `ack: "stored"`; after an unknown outcome the same ciphertext is sent again and blocks the next number
until it is confirmed, so a retry can only produce a repeat, never a gap or two texts under one number. (6) The
client reads the windows newest first and handles them oldest first, so a message is never seen before one that
precedes it. (7) Both ends show a fingerprint of the transcript.
Consequences: no forward secrecy and no ratchet: a prekey that leaks opens every conversation agreed with it, past
and future (ISSUE-28). The server distributes the prekeys and can replace one; only the fingerprint comparison, which
is manual, detects that. The open fetch lets anyone list which names have a prekey (registration already tells which
names exist) and is not rate-limited. A reader cannot detect the loss of a sender's last messages or of a whole
session; the sender detects the first for its own messages. The session id restarts the numbering when a client
restarts, so a restarted client needs no stored counter. The order between the two senders is not verifiable.
A client reads on a fixed schedule, not when it expects a message (ADR-018).

## ADR-020 — Browser client: the SDK's protocol in WebCrypto (X25519, not P-256), key handles in IndexedDB, reads on a fixed schedule — ACCEPTED — 2026-10-12
Context: M13 S3 names "ECDH P-256 + HKDF → AES-256-GCM" for the browser, while M12 (ADR-019) fixed the client
protocol as X25519 + HKDF with a token and a header that docs/API.md describes byte for byte. Two agreements would
make two incompatible clients. M13 also leaves open where a pane's account comes from and when a pane reads.
Decision: (1) The page implements the protocol of docs/API.md "The client" unchanged, with WebCrypto's X25519
(`web/js/crypto.js`, `web/js/client.js`); a pane and the Python SDK interoperate, and a test proves it. P-256 is used
only where the server requires it: the ES256 device key of the DPoP proofs. A browser without X25519 in WebCrypto
gets a message in the pane, not a fallback. (2) The device key and the prekey are generated with
`extractable: false` and stored in IndexedDB as CryptoKey handles, one pair per pane; K_content is imported as a
non-extractable AES-GCM key. (3) Each pane has a demo account of its own, created by the page: a random name and a
random password kept beside the handles. The password is readable by script; what binds a session is the device key.
(4) A pane starts at the open window without a strict start (the first number it sees of a session is where that
session begins for it), because a page reload begins in the middle of a conversation. (5) Both panes read once a
second whether or not anything was sent, not after a send and not on every tick: a read schedule that follows the
typing would tell the server when a pane expects a message. (6) `/app` is served with a CSP that allows scripts,
styles and connections from the same origin only; `style-src-attr 'unsafe-inline'` stays until the prototype's
charts stop using `style=` attributes (ISSUE-29).
Consequences: a message shows up to about a second after it was stored. A pane cannot detect the loss of messages
sent before the first one it saw of a session (ISSUE-28 point 2 applies to it more widely than to the strict SDK
reader). Script running in the page can use the keys while it runs; the CSP is the defence against that, and it is
untested against a real injection. The page needs a browser with X25519 in WebCrypto and a secure context (https,
or http on loopback); it was run in Chrome only.

## ADR-021 — Server view: `/v1/dump` hands out stored rows only; the true order is worked out in the page; the panel spans closed windows — ACCEPTED — 2026-10-12
Context: M13 S4 asks for a panel with the stored rows "for the current window" and a dev toggle that overlays each
row's real send index. Two things in that sentence do not hold in the system as built. (a) The open window is not
shuffled as a whole: the scheduler stores one permuted batch per epoch and re-shuffles a window only after it closed
(ADR-004), so rows typed seconds apart lie in arrival order while the window is open. A panel of the current window
alone would show the order of sending. (b) The server could produce the send index only by opening `seq_enc` with
`K_seq` for a debug route.
Decision: (1) `GET /v1/dump?limit=&windows=` (with `--dev`; 403 `dev_only` otherwise, also for malformed queries)
returns the rows of the newest windows in physical order with the state of each window (`open`, `closing`,
`reshuffled`, `epoch`, `arrival`), read through `Repo.window_rows` in the engine thread. It uses no key. (2) The
overlay is computed by the page: a verified message keeps the ciphertext the server returned for it, and a stored
row is matched to a message by its payload bytes. The number shown is the position in the conversation as a pane
read and verified it since the page opened, with the sender. (3) The panel shows the windows of the last 240 s (at
least 2, at most 64 windows, at most 200 rows), marks the state of each row's window and says in its note that the
open window still lies in epoch order. (4) Without `--dev` the page does not ask for the rows at all. (5) The M10
contract test that expected 404 for `/v1/dump` now expects the 403.
Consequences: the server never decrypts a sequence number for the demo, and the overlay doubles as a statement that
only the clients know the order. The overlay is empty for rows no pane has read (after a reload, other
conversations). The dump carries full payloads (4124 B each), so the page fetches up to about 1 MB a second on
loopback in dev. The route is unauthenticated in dev (ISSUE-30).

## ADR-022 — Mode switch: a comparison backend that writes both stores (`serve --dev --compare`); the mode selects which one answers — ACCEPTED — 2026-10-12
Context: M13 S5 asks for `/v1/mode` (dev) to flip between `vcloak` and `baseline` "so the same conversation can be
dumped both ways". The two modes are two backends over two stores (M10): a switch that only exchanged the backend
would show an empty panel after every flip, and two different conversations side by side prove nothing. ISSUE-30
left two points for this step: `/v1/dump` reachable from another host with `--dev`, and a baseline dump without the
columns that table holds in the clear.
Decision: (1) `service/switch.py` `SwitchBackend` owns a `VcloakBackend` and a `BaselineBackend` on one clock. Every
accepted message goes to both: the scheduler first (only it can refuse; a refused message reaches neither store),
then the baseline insert, so that table is in arrival order whatever acknowledgement the sender waits for. Reads, the
dump, the counters and `mode` come from the active one. (2) It is built only by `serve --dev --compare`; `serve`
refuses `--compare` without `--dev` and with `--visible-round epoch`. Plain `--dev`, and every measurement (M14, M15),
keep the single backend. (3) `GET /v1/mode` is open; `POST /v1/mode` answers 403 `dev_only` without `--dev` and 409
`not_switchable` without `--compare`; `/v1/stats/live` carries `switchable`. (4) `serve` refuses `--dev` on a host
that is not loopback, whatever else is given (ISSUE-30 point 1). (5) The baseline dump returns `ts` and `conv`
(`BaselineStore.dump_clear`; `dump()` is unchanged for M14), and the panel shows them in place of `bucket` and
`seq_enc` with a caption on what each layout leaks (ISSUE-30 point 2). (6) After a switch the page holds both panes,
changes the mode, and has them read their open windows again (`Client.reread`): the per-window payload count is
reset, the per-sender message numbers are kept, so a repeat is dropped and a gap is still flagged.
Consequences: with `--compare` the server holds exactly the table V-cloak exists to avoid. It is a dev-only
demonstration and the panel says so on screen; it must never be described as a deployment feature. No timing taken
on a `--compare` server is a result. The two stores can disagree by one window about a message near a boundary, so a
client that is not told about the switch (the Python SDK, a second tab) can stop with an order error. The M10 test
that started `--dev` on `0.0.0.0 --allow-remote` now runs without `--dev`.

## ADR-023 — P3 is claimed for the kernels; the timing of the host orchestration is outside the threat model — ACCEPTED — 2026-10-13
Context: ISSUE-17 point 2 left one question to the team: is the host Python of `write_epoch` inside the threat
model? The dudect series that contain host code FAIL with EQUAL contents in both classes (the whole call, the
transfers, and the engine's stage intervals, which hold the host code that issues the launches; ISSUE-17, ISSUE-25).
The human decided it on 2026-10-13 (session 32), as reported in the session request; the agent records it.
Decision: (1) The adversary of `ai/PROJECT_BRIEF.md §3` is passive and holds a snapshot of the persistent store. A
dump carries no timing. Observing the running time of the server needs a compromised running backend, which §3
already puts out of scope. (2) P3 (§4) is worded for the kernels: "the kernels' access trace and running time".
The claim of the project is therefore obliviousness of the server-side kernels; the timing of the host
orchestration (Python: building rows, issuing launches, transfers of host memory) is NOT claimed. (3) The claim is
not widened: no document may say that `write_epoch`, the write path or the service is constant time. (4) The
kernel-level claim is tested with a window that holds no host code (ISSUE-25, group `issue25k` of
`bench/run_dudect.py`), beside the SASS reading and the E3 trace invariance.
Consequences: a whole-call or per-stage FAIL with equal contents is a property of the host code and of the
harness, reported as measured and listed as a limitation (generated text of `report_oblivious`, section 4.O.6); it
is never removed from a table, and it no longer blocks M14 by itself. What still has to be shown for the kernels
is what ISSUE-25 measures. M14 and the report must state the scope in these words: kernel-level obliviousness,
against an adversary who sees the store and no timing. A reader who assumes a co-located or network timing
attacker is told that this is outside the model, not that it was defeated. This ADR does not change any verdict or
any row of `state/METRICS_INDEX.md`.

## ADR-024 — Performance comparisons come from one runner platform; every provenance line carries the vCPU count — ACCEPTED — 2026-10-13
Context: the before-measurement of the row-id change of ISSUE-12 was taken on Kaggle (4 vCPU, session 20261011-213139);
the job for the after-measurement (20261013-163732_M07_issue12) was packed without naming a platform and was run on
Colab (2 vCPU). The host stage of `write_epoch` is Python on the CPU of the runner, so the two runs cannot be
compared, the run was UNSTABLE in all 12 configurations, and a session was spent on numbers that are not values.
The owner decided the rule on 2026-10-13 (session 44), as reported in the session request; the agent records it.
Decision:
1. A before/after comparison, and any comparison between configurations, is made only between runs of the same
   runner platform: the same provider (colab or kaggle) and the same vCPU count. If the image differs (CUDA
   runtime, driver), the difference is stated beside the numbers. A comparison across platforms is recorded as
   NOT_MEASURED; an ID that occurs in two sessions names two measurements, never a before and an after.
2. A job whose numbers will be compared with an earlier run names the platform of that run in its spec
   (`runner_required`, `cpu_count_required`). `scripts/gpujob.py pack` copies both keys into job.json and
   `colab/gpu_entry.py` refuses to run the job on another platform, before any command starts. The GPU JOB READY
   issue names the platform first.
3. The provenance line of every generated section names the vCPU count beside the GPU name. New run manifests
   carry `env.cpu_count` (`vcloak.runs.build_env`); for runs taken before this ADR `vcloak.runs.runner_vcpu` reads
   the count the runner wrote into `result.json` of the ingested bundle (`gpujobs/done/`). Where neither exists the
   line says NOT_MEASURED. The count is never typed by hand.
4. An UNSTABLE configuration is not a value (gpu-bench rule 5): its attempts are not quoted as numbers in an issue,
   the notes or the report, and no gate verdict is read from them.
Consequences: gpu-bench rules 8 to 10 (`.claude/skills/gpu-bench/SKILL.md`). The M07 section already printed the
CPU as `<model> x<count>`; the M08 and M14 sections were regenerated with the count
(runs/20261013-171026_M16_prefixes/report_command.txt). This ADR changes no measured value.

## ADR-025 — A PC with a discrete NVIDIA GPU is a third runner under the job protocol, named `pc-<gpu>` — ACCEPTED — 2026-10-13
Context: Kaggle refuses the GPU performance counters (ISSUE-18), and that is a setting of the machine that owns the
GPU. The owner has access to a PC with a discrete NVIDIA GPU and decided on 2026-10-13 (session 46, in the session
request) to use it as a runner. The project does not move there: the laptop stays the place of all development,
packing and ingest. The agent records the decision.
Decision:
1. The PC is a runner like Colab and Kaggle (ai/GPU_RUNNER.md section 4): the same `gpu_entry.py` from inside the
   job zip, the same results zip, the same ingest checks. The kit that starts it is `pc_runner/` (SETUP.txt, RUN.txt,
   `check_setup.py`, `run_job.py`, `verify_result.py`); it is not part of a job bundle.
2. Its runner name is `pc-<gpu>`, derived by the kit from the GPU that nvidia-smi reports, and never `local`.
   `local` stays the GPU-less laptop, whose numbers are never a GPU result (`scripts/check_metrics.py`).
   `vcloak.runs.validate_manifest` accepts `colab`, `kaggle`, `local`, `unknown` and `pc-<gpu>`.
3. ADR-024 applies unchanged: the PC is a platform of its own (another GPU model, CPU, driver and operating
   system). Nothing measured there is compared with, pooled with, or put in one figure with a Colab or Kaggle run,
   and no existing T4 number is replaced by a PC number.
4. The `runner` block of STATE.md and docs/ENV.md describe the Kaggle T4 of the M00 probe. A probe from the PC is
   ingested as a run of its own; whether `scripts/record_env.py` is run for it is decided at that ingest.
5. Hard rule 2 of CLAUDE.md says the GPU is remote and names Colab and Kaggle. Read with this ADR: the measurement
   device is a runner reached through the job protocol, and no GPU metric exists outside an ingested bundle.
Consequences: `bench/jobs/M08_ncu.json` (the ncu step alone, for ISSUE-18). `bench/run_ncu.py` and `gpu_entry.py`
start `ncu` by the path `shutil.which` resolves, because on Windows it is a .bat file. This ADR changes no
measured value. The Windows and WSL2 paths of the kit have not been run by the project when this is written.
