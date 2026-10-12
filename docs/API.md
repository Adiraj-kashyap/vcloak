# V-cloak service API (v1)

The backend of `vcloak serve` (M10). Authentication (DPoP, sessions, the WebSocket) is added by M11 and will
get its own section here; until then the service must only listen on localhost: `vcloak serve` refuses a
`--host` that is not a loopback address unless `--allow-remote` is given.

All bodies are JSON. Unknown fields are rejected. The same contract is served in both modes
(`--mode vcloak` and `--mode baseline`); `tests/service_contract.py` runs one set of tests against both.

## Run

```
vcloak serve --mode vcloak|baseline --clock wall|sim [--visible-round window|epoch] [--dev]
             [--store pg|sqlite] [--dsn DSN] [--schema NAME] [--key-file PATH]
             [--host 127.0.0.1] [--allow-remote] [--port 8000]
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
| `conv_token` | The client's opaque handle for one conversation: 16 to 128 characters of `A-Z a-z 0-9 _ -`. Both ends of a conversation derive the same token (M12). The server hashes it to the 64-bit conversation id of the engine (ADR-015). M11 binds it to the session. |
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
never logged; a field outside the allow-list raises. Nothing is logged per epoch: the scheduler reports once per
closed window.
