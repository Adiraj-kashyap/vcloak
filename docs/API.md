# V-cloak service API (v1)

The backend of `vcloak serve` (M10). Sessions (M11) are described under *Sessions and DPoP* below:
`vcloak serve --sessions` switches them on. Without `--sessions` the API is open, and the service must then only
listen on localhost: `vcloak serve` refuses a `--host` that is not a loopback address unless `--allow-remote` is
given. The service speaks plain HTTP: on any other address put TLS in front of it and pass the public URL with
`--public-origin https://...` (it is what a proof must name in `htu`).

All bodies are JSON. Unknown fields are rejected. The same contract is served in both modes
(`--mode vcloak` and `--mode baseline`); `tests/service_contract.py` runs one set of tests against both.

## Run

```
vcloak serve --mode vcloak|baseline --clock wall|sim [--visible-round window|epoch] [--dev]
             [--store pg|sqlite] [--dsn DSN] [--schema NAME] [--key-file PATH]
             [--host 127.0.0.1] [--allow-remote] [--port 8000] [--sessions] [--public-origin URL]
             [--slots N] [--buckets N] [--window-s N] [--epoch-ms N] [--cand-k N]
```
(`python -m vcloak.cli serve ...` is the same command.)

| Option | Meaning |
|---|---|
| `--mode vcloak` | The protected path: epoch scheduler, GPU engine, permuted store. |
| `--mode baseline` | The unprotected comparison (M14, M15): arrival-order inserts with a serial id and a timestamp, in the schema `baseline`. Never a deployment mode. |
| `--clock wall` | Epochs close on wall-clock multiples of `EPOCH_MS`. |
| `--clock sim` | A virtual clock that jumps from boundary to boundary as fast as the engine and the store allow (M14). |
| `--visible-round window` | Default. The stored round is the window; a closed window is re-shuffled once (ADR-004). |
| `--visible-round epoch` | The Review-1 layout: the stored round is the epoch, nothing is re-shuffled. For the M14 comparison only. On the wall clock the rounds are counted from 2026-01-01T00:00:00Z. |
| `--dev` | Use the fixed public development key. Without it the master key is unsealed from `--key-file` (or `VCLOAK_KEY_FILE`, default `secrets/k_master.sealed`) with the passphrase in `VCLOAK_PASSPHRASE`, or typed at a prompt. The variable is removed from the process environment once read. |
| `--store sqlite` | An in-memory store for demos and tests. Evaluation numbers come from PostgreSQL only (ADR-008). |

On shutdown the service stops accepting submissions, writes what is queued on the next epoch boundaries, and
zeroizes the device keys. The request log is off: a line per request would be an arrival record.

### Restart and crash (ADR-016)

The store keeps a list of the windows that still hold the layout they were written in (`pending_windows`: a
window id per row, nothing else). A window is listed before its first rows are stored and comes off the list in
the transaction that swaps in its re-shuffled partition. At startup the service reads the list; the first epoch
it writes re-shuffles every listed window that has closed, including windows that closed while the service was
down. A window is therefore re-shuffled once, whether the service was stopped, killed or interrupted during the
re-shuffle itself. `scripts/smoke_restart.py` kills a live server in the middle of a window and checks this on
PostgreSQL.

The queue of accepted messages is in memory only, on purpose: a journal of it on disk would be a record of the
arrival order, which is what the store must not hold. A shutdown writes the queue; a kill loses it (up to one
epoch of messages, more while epochs overflow). A client that needs to know sends `"ack": "stored"` (below).

## Values

| Name | Form |
|---|---|
| `conv_token` | The client's opaque handle for one conversation: 16 to 128 characters of `A-Z a-z 0-9 _ -`. Both ends of a conversation derive the same token from their content key (*The client*, below). The server hashes it to the 64-bit conversation id of the engine (ADR-015). A session does not bind it: the token is a capability, and the server keeps no user-to-conversation relation (ADR-017). |
| `payload_b64` | Standard base64 of one client ciphertext. It must decode to exactly `12 + BLOCK + 16` bytes (nonce, padded block, tag): every stored message has the same size. |
| `win` | A visible round: `floor(unix_seconds / WINDOW_S)` in window mode. An integer from 0 to 2^31 - 2. |

## Routes

### `POST /v1/messages`
Request `{"conv_token": "...", "payload_b64": "...", "ack": "queued"}`; `ack` is optional.

| `ack` | Answer | Meaning |
|---|---|---|
| `"queued"` (default) | `202 {"accepted": true, "stored": false}` | The message is in the queue of the open epoch. It is lost if the service is killed before that epoch is written. |
| `"stored"` | `201 {"accepted": true, "stored": true}` | Sent after the epoch that carries the message is committed to the store: the message survives a kill. The answer comes at an epoch boundary, so it takes up to `EPOCH_MS`, longer while epochs overflow. |

With `"stored"`, a `503 not_stored` says the service stopped before the write (the message is not stored: send
it again). A `504 ack_timeout` or a broken connection leaves the outcome unknown: the message may still be
written. The service keeps no message identity, so a repeated message is stored twice; a client that retries
must carry its own message number inside the plaintext and drop repeats when it reads (M12).

In V-cloak mode the message is queued for the epoch that is open now and written when that epoch closes. If more
than `SLOTS` messages arrive in one epoch, the first `SLOTS` are written and the rest go into the next epoch, in
arrival order; the epoch is never extended. The answer does not say which window the message lands in: read the
window that was current when it was sent, and the next one. In baseline mode the message is stored before the
answer is sent.

The server assigns the order of a conversation: messages are returned in the order the server accepted them.

### `POST /v1/read`
Request `{"conv_token": "...", "win": 29363120}`. Answer `200 {"win": 29363120, "payloads_b64": ["...", ...]}`:
the payloads of that conversation in that round, in order. An unknown conversation or an empty round gives an
empty list.

In V-cloak mode the server fetches exactly `CAND_K` candidate rows for the conversation's bucket and round and
opens them on the GPU; the number of rows it touches does not depend on the conversation.

### `GET /v1/windows`
Answer `200 {"win": 29363120, "window_s": 60, "epoch_ms": 200, "visible_round": "window", "mode": "vcloak"}`:
the round being written now and the public parameters a client needs to walk the rounds.

### `GET /healthz`
Answer `200 {"status": "ok", "mode": "vcloak", "ready": true, "epochs": 0, "overflow": 0, "missed": 0, "queued": 0}`.
`ready` says the device keys are loaded. The counters are public and are zero in baseline mode:

| Counter | Meaning |
|---|---|
| `epochs` | Epochs written since the start. |
| `overflow` | Messages left for a later epoch because the epoch was full (counted once per epoch they waited). |
| `missed` | Epoch boundaries that passed while an earlier epoch was still being written. |
| `queued` | Messages accepted and not yet written. |

### `GET /v1/stats/live` (M13)
Open, like `/v1/windows`. Answer `200 {"mode": "vcloak", "dev": true, "sessions": true, "win": 29363120,
"window_s": 60, "epoch_ms": 200, "slots": 64, "queued": 0, "epochs": 12, "payload_len": 4124, "gpu": null}`:
public parameters, the public counters of `/healthz`, and what the web page needs to decide how to run. `dev` and
`sessions` say how the service was started; `payload_len` is the size every `payload_b64` must decode to; `slots` is
null in baseline mode. `gpu` is null for now (the provenance of the compute backend is added with the live strip).

### `GET /app/` (M13)
The web app: the files of `web/` as they are on disk (`/app` redirects to `/app/`). Every answer under `/app` carries
`Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; style-src-attr 'unsafe-inline';
img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'`,
`X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and `Cache-Control: no-store` with `--dev`
(`no-cache` without). The page needs `--sessions` to chat; see docs/DEMO.md.

## Sessions and DPoP (M11, ADR-017)

An app created with a `SessionService` (`create_app(backend, sessions=...)`, or `vcloak serve --sessions`) has the
routes below, and
`POST /v1/messages` and `POST /v1/read` then need a session. `GET /v1/windows` and `GET /healthz` stay open.
Session state is in memory: a restart logs every client out and forgets the accounts.

### The client key and the proof
A client device makes one ES256 (P-256) key pair and keeps the private key. Every request that needs a session
carries a fresh DPoP proof (RFC 9449) in the `DPoP` header: a JWS signed by that key with

- header `{"typ": "dpop+jwt", "alg": "ES256", "jwk": {"kty": "EC", "crv": "P-256", "x": "...", "y": "..."}}`
- claims `htm` (the method), `htu` (the URL without query and fragment), `iat` (now, in seconds), `jti` (a fresh
  random value of 16 to 128 printable characters) and, when an access token is sent, `ath` = base64url(SHA-256(token)).

and the access token in `Authorization: DPoP <access_token>`. The token is bound to the key: its `cnf.jkt` is the
RFC 7638 thumbprint of the JWK. The server evaluates every check and then decides:

| Check | Holds when |
|---|---|
| `proof_format` | exactly one `DPoP` header, three base64url parts, JSON objects, a 64-byte signature, at most 4096 characters |
| `typ`, `alg`, `jwk` | `dpop+jwt`, `ES256`, a P-256 public key on the curve without a private member |
| `signature` | the ES256 signature verifies under the `jwk` of the header |
| `htm`, `htu` | the method, and the URL in normal form (lower-case scheme and host, default port dropped), are those of the request |
| `iat` | within 60 s of the server clock |
| `jti` | not seen in the last 300 s (remembered only for accepted requests) |
| `authorization` | `Authorization` has the scheme `DPoP` and one token |
| `token_format`, `token_mac` | the token is the server's JWS and its HMAC holds |
| `token_exp` | the token is younger than 600 s |
| `token_revoked` | the login it belongs to has not been logged out or revoked |
| `key_binding` | the thumbprint of the proof's key equals `cnf.jkt` of the token |
| `ath` | the proof names the hash of this token |

A refused request gets 401, `{"error": "invalid_dpop_proof" | "invalid_token", "failed_check": "<first failed check>"}`
and `WWW-Authenticate: DPoP error="...", error_description="<check>", algs="ES256"`. The session is checked
before the body, so a request without one never gets a 422.

### `POST /v1/auth/register`
Request `{"username": "...", "password": "..."}`: a name of 3 to 32 characters of `a-z 0-9 _`, a password of 8 to
128 characters. The password is stored as an Argon2id hash only (t=3, m=64 MiB, p=4, a salt per user, the
parameters in the hash string). Answers 201 `{"registered": true}`, 409 `{"error": "username_taken"}`, or 429.

### `POST /v1/auth/login`
Request `{"username": "...", "password": "..."}` with a `DPoP` proof (no `ath`): the new tokens are bound to the
key of that proof. Answers 200
`{"access_token": "...", "refresh_token": "...", "expires_in": 600, "token_type": "DPoP"}` with
`Cache-Control: no-store`; 401 `{"error": "invalid_credentials"}` for a wrong password and for an unknown name
alike; 401 with the DPoP challenge for a bad proof; 429 `{"error": "rate_limited"}` with `Retry-After`.
Limits: 20 attempts per address per 60 s; 5 attempts per name per 300 s without a success in between;
registration 5 per address per hour.

### `POST /v1/auth/refresh`
Request `{"refresh_token": "..."}` with a `DPoP` proof of the same key (no `ath`). A refresh token works once:
the answer (as for login) carries the next one. 401 `{"error": "invalid_grant", "reason": "..."}` otherwise:

| `reason` | Meaning |
|---|---|
| `reuse` | the token was already spent: every token of that login is revoked now. Log in again. |
| `family_revoked` | the login was logged out or revoked |
| `key_binding` | the proof was signed by another key than the login's (the token is not spent) |
| `expired`, `unknown` | older than 7 days, or not a token of this server (a restart forgets them all) |

### `POST /v1/auth/logout`
No body; `Authorization` and `DPoP` as for any authenticated request. Answers 204. The access tokens and the
refresh tokens of that login stop working at once; other logins of the account are not touched.

### `PUT /v1/prekeys` and `GET /v1/prekeys/{username}` (M12, ADR-019)
`PUT` with `{"prekey_b64": "..."}` (a public X25519 key: 32 bytes, standard base64), `Authorization` and `DPoP` as
for any authenticated request: sets the prekey of the account of the session. The newest replaces the one before.
Answers 204. `GET` takes **no session**: it answers 200 `{"username": "...", "prekey_b64": "..."}`, or 404
`{"error": "no_prekey"}` for an unknown name and for an account without a prekey alike. The fetch is open on
purpose: with a session the server would learn which account asked for whose key. Prekeys are in memory with the
accounts. The server could hand out a key of its own: the two clients compare a fingerprint (below).

### `POST /v1/auth/ws-ticket`
No body; `Authorization` and `DPoP` as for any authenticated request. Answers 200
`{"ticket": "...", "expires_in": 30}` with `Cache-Control: no-store`. A ticket opens one socket, within 30 s, for
the key of the request that asked for it. A login holds at most 8 unspent tickets (the oldest goes first).

### `WS /v1/ws` (ADR-018)
The server pushes one text frame after every epoch boundary: `{"type": "tick", "win": <visible round>}`. **Every
socket gets the same frame**: it says that a boundary passed, never whose messages arrived, and a client reads
with `POST /v1/read` when it chooses to. A socket slower than the cadence misses frames; none is queued.

1. Open the socket (no header, nothing in the URL).
2. Within 5 s send one text frame `{"ticket": "<ticket>", "dpop": "<proof>"}`. The proof is a DPoP proof with
   `htm` = `GET` and `htu` = the URL of the socket written as `http://` or `https://` (not `ws://`), no `ath`,
   signed by the key the ticket was issued to.
3. The server answers `{"type": "ready", "win": N}` and then pushes. The client sends nothing more.

The server evaluates the nine proof checks above and six ticket checks, then decides; the ticket is spent only
when the socket opens.

| Check | Holds when |
|---|---|
| `ticket_format`, `ticket_known` | 43 base64url characters; a ticket this server issued and still remembers |
| `ticket_unused` | it has not opened a socket yet |
| `ticket_exp` | it is younger than 30 s |
| `ticket_session` | the login it belongs to has not been logged out, revoked or expired |
| `ticket_key` | the proof is signed by the key the ticket was issued to |

| Close code | Reason | When |
|---|---|---|
| 4401 | the first failed check | the proof or the ticket did not verify |
| 4408 | `auth_timeout` | no first frame within 5 s |
| 1008 | `auth_frame`, `unexpected_frame` | the first frame is not the object above (or exceeds 8192 characters); any later frame from the client |
| 4429 | `too_many_sockets` | the login already holds 4 sockets, or the service 1024 |
| 4001 | `session_ended` | logout, a detected refresh reuse (at once), or the login expired (at the next boundary) |
| 1001 | `shutdown` | the service stops |

A socket lives as long as its login (refreshing keeps it), not as long as one access token.

## The client (M12)

`vcloak.client.sdk.VcloakClient` is the reference client; `vcloak-chat --server URL --user NAME --peer NAME` is a
terminal chat on top of it, and `python scripts/demo_two_users.py` runs two of them against a live service.

| Step | What the client does |
|---|---|
| Keys | One ES256 key per device for the proofs and one X25519 prekey, both in memory. `vcloak-chat --keyfile` keeps them in a file sealed with Argon2id + AES-256-GCM under a local passphrase. |
| Agreement | `K_content = HKDF-SHA256(X25519(own prekey, peer prekey), info = "vcloak-content-v1" + transcript)`; the transcript is both prekeys in sorted order and both account names. |
| Token | `conv_token = base64url(HKDF-SHA256(K_content, info = "vcloak-conv-token-v1", 24 bytes))`: 32 characters, the same at both ends, one-way. |
| Fingerprint | 30 digits of SHA-256 over the transcript, shown at both ends, to be compared over another channel. |
| Message | plaintext = `version(1)=1, sender(1), session(8), number(LE64), text (UTF-8)`, padded to `BLOCK`, AES-256-GCM with the token in the associated data. At most `BLOCK - 19` bytes of text. |
| Send | `POST /v1/messages` with `"ack": "stored"`. 503: again after `Retry-After`. 504 or a broken connection: the same ciphertext again; the number is not reused for another text until the message is confirmed. |
| Read | The windows from the start of the conversation to the open one, newest first, handled oldest first. For each (sender, session) the numbers must come as 0, 1, 2, ...: an accepted number again is a repeat and is dropped; a higher one is a missing or reordered message (`SequenceError`); a payload that does not authenticate is `TamperError`. |

The page at `/app` is a second client with the same rules and the same bytes (`web/js/crypto.js`, `web/js/client.js`,
WebCrypto only): a pane and the SDK compute the same token and fingerprint and read each other's messages
(`tests/integration/test_web_app.py`). Its two differences: the private keys are non-extractable handles in
IndexedDB instead of a sealed file, and a pane starts reading at the open window without a strict start.

A reader alone cannot see the loss of a sender's *last* messages, or of a whole session it saw nothing of; the
sender checks that every message the store confirmed comes back (`verify_delivered`). The order between the two
senders is the server's arrival order and is not verifiable. The agreement uses one static prekey per device:
there is no forward secrecy and no ratchet (ISSUE-28).

## Errors

| Status | Body | When |
|---|---|---|
| 422 | `{"error": "invalid_request", "fields": [{"field": "payload_b64", "reason": "payload_size"}]}` | A missing, unknown or malformed field, or a payload of the wrong size. The answer names the field and the reason, never the rejected value. |
| 503 | `{"error": "queue_full"}` with `Retry-After: 1` | The submission queue is at its bound (16 epochs of `SLOTS` by default), or the service is shutting down. |
| 503 | `{"error": "not_stored"}` with `Retry-After: 1` | `ack: stored` only: the service stopped before the message was written. |
| 504 | `{"error": "ack_timeout"}` | `ack: stored` only: the message is still queued after every epoch the queue could hold had time to close (at least 5 s). It is not withdrawn. |
| 503 | `{"error": "candidate_overflow"}` | A bucket-round holds more than `CAND_K` rows. `CAND_K` is a capacity limit: the read fails instead of returning a truncated conversation (ADR-014). |

## Logging

Application code logs through `vcloak.service.logsafe` only: an event name and allow-listed public fields
(counts, the window, public parameters, an exception class name), with a timestamp of one-second resolution.
Conversation tokens and ids, buckets, sequence numbers, row ids, epoch numbers, payload bytes and key material are
never logged, and neither are tokens, tickets, proofs and their `jti`, key thumbprints, account names and client
addresses; a field outside the allow-list raises. `vcloak serve` runs without an access log and drops the HTTP
server's per-connection lines (`"WebSocket /v1/ws" [accepted]`, `connection open`): with the peer address and the
time they are an arrival record. Nothing is logged per epoch: the scheduler reports once per
closed window.
