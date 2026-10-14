# Demo guide

How to show V-cloak running. This file grows with the frontend: the chat section is M13 (steps S1-S6);
the dashboard is M18.

## 1. The chat

### Start
```
python -m vcloak.cli serve --dev --compare --sessions --store sqlite --window-s 5
```
then open `http://127.0.0.1:8000/app/` in Chrome or Edge. `--store sqlite` needs no database; leave it out to use
PostgreSQL (`docker compose up -d --wait db` first). `--dev` uses the public development key: a demo database only.
Use `127.0.0.1` or `localhost`: WebCrypto exists only in a secure context, and plain http counts as one on loopback
only. The chip at the top right must read **live · dev**. `--compare` is what makes the "Unprotected baseline" switch
work (see "The same conversation both ways"); `--window-s 5` closes a window every five seconds, so the shuffle shows
quickly. Both are for the demonstration only.

If the backend is down, open `web/index.html` from the file manager instead: the chip reads **demo data**, the
conversation is local to the page and the rows under it are bundled sample rows, not a result.

### What is real on the screen
| On screen | What it is |
|---|---|
| User A, User B | Two clients in one page. Each has its own account (`alice_…`, `bob_…`), its own ES256 device key, its own X25519 prekey and its own login. Nothing is passed from one pane to the other inside the page: B shows a message only after B's client read it from the server and decrypted it. |
| `ES256 jkt …` | The RFC 7638 thumbprint of the pane's device key. Every request of the pane carries a DPoP proof signed by that key; the server binds the tokens to it. |
| `#3 · window 29363120 · verified` | The sender's message number (it is inside the ciphertext), the window the server returned it in, and the fact that the pane checked the numbering. |
| Key fingerprint | 30 digits over both prekeys and both account names, computed by each pane. Equal digits mean both panes hold the same keys; the server hands out the prekeys, so this comparison is what would expose a replaced one (ISSUE-28). |
| A red bar in a pane | The order or the content check failed: a message is missing, out of order, or not a ciphertext of this conversation. The pane stops showing messages there. |

A message appears in both panes up to about a second after Send: the sender waits for the server to confirm that the
message is stored (`ack: "stored"`, up to one epoch), and both panes read once a second on a fixed schedule whether
or not anything was sent.

### Where the keys are (presenter note 3)
The device key and the prekey are generated in the browser with `extractable: false` and kept in IndexedDB as
`CryptoKey` handles. A handle can sign and derive; `crypto.subtle.exportKey` on it rejects
(`test_the_private_keys_cannot_be_exported`: `InvalidAccessError` for jwk, pkcs8 and raw, for both panes, and for the
AES content key). The content key is derived inside WebCrypto and imported as a non-extractable AES-GCM key; its
bytes pass through script once, during the derivation, and are overwritten.

What that does and does not give:
- Script injected into the page could *use* a key while the page is open (sign a proof, decrypt a message). It
  could not copy the key out and use it elsewhere or later.
- The Content-Security-Policy of `/app` is what keeps foreign script out: scripts only from the server's own origin,
  no inline script, connections only to the same origin.
- The keys are per browser profile. Clearing the site data removes them; the panes then make new keys and new
  accounts.
- The pane's account password is random, made in the browser, and stored next to the handles in readable form. It
  only satisfies the login route of the demo accounts; a real client would ask the user for it.
- The server forgets accounts at a restart (ISSUE-26). The panes then register the same names again by themselves.

### What the server stores (presenter note 1)
The panel under the panes is `GET /v1/dump`: the rows of the last windows exactly as the store holds them, top to
bottom in physical order. It needs `--dev`; without it the route answers 403, the panel says so and "Reveal true
order" stays disabled.

| Column | What it is |
|---|---|
| `row_id` | A random UUID per row, new again after the re-shuffle. No serial number. |
| `bucket` | `PRF(K_bkt, conversation) mod BUCKETS`: all rows of one conversation share it, and so do other conversations. |
| `win` | The window the row was stored in, with its state: `open`, `closing` or `re-shuffled`. |
| `seq_enc` | 44 bytes: the position of the message, sealed under the server's `K_seq` (first and last bytes shown). |
| `payload` | The client's ciphertext, one fixed size for every message (first and last bytes shown). |
| `sent` (Reveal true order) | `#n U`: the row is message n of the conversation, sent by user U. |

How to show it: send eight or so messages within one window, wait for the window to close (`--window-s 5` makes that
quick), switch "Reveal true order" on. The rows of the closed window carry numbers that are not in order.

What to say, and what not to:
- The revealed number does not come from the server. Each pane keeps the ciphertext of every message it read back and
  verified; the page looks up each stored payload among them. A row shows "—" when no pane has read it since the page
  was opened (after a reload, or a row of another conversation).
- The **open** window is not shuffled as a whole yet: each epoch is permuted, but the epochs lie in arrival order
  until the window closes. Messages typed seconds apart are in different epochs, so in the open window the revealed
  numbers ascend. That is the design (the re-shuffle of a closed window is what hides the order), and the panel's
  note says so. Do not point at the open window as the result.
- The panel still shows what the store leaks: which window a row is in, how many rows a window holds, and the bucket.
- With few rows a permutation can leave some rows where they were; the order is a pseudo-random permutation keyed by
  the window, not a guarantee that every row moves.

### The same conversation both ways (presenter note 1)
With `--dev --compare` the server keeps an ordinary message table beside the V-cloak store and writes every message
to both. "Unprotected baseline" (`POST /v1/mode`) chooses which of the two the panel, and the panes, are served from.
Nothing else changes: the same ciphertexts, the same clients.

How to show it: send eight or so messages, wait until their window is marked `re-shuffled`, switch "Reveal true order"
on, then flip "Unprotected baseline" back and forth.

| | V-cloak | Baseline |
|---|---|---|
| Row id | random UUID, new after the re-shuffle | serial number: 1, 2, 3 … |
| `ts` | no such column | arrival time of each message, in the clear |
| `conv` | no such column (a `bucket` shared with other conversations) | the conversation id, in the clear |
| Order of the rows | the engine's permutation of the closed window | the order of arrival |
| Revealed numbers | not in order | 1, 2, 3 … top to bottom |

What to say, and what not to:
- In the baseline the message text is still encrypted. What the table gives away without any key is everything
  around it: who is in a conversation with whom, when each message came, and the order.
- The baseline table exists on this server because of `--compare`, and the panel's note says so. A V-cloak server
  does not keep one. Never present the switch as something a deployment has.
- The switch needs `--compare`; on a server started without it the switch is disabled and the route answers 409.
- Flip the mode with one page open. The panes read their open windows again after a switch, because the two stores
  can file a message under neighbouring windows; another client connected at that moment (the Python SDK, a second
  tab) is not told and can stop with an order error.
- The switch compares layouts, not speed. No timing on this page is a result, and with `--compare` every message is
  written twice.

### Taking the pictures
`python scripts/capture_evidence.py --module M13` starts its own server (`serve --dev --compare`, SQLite, the engine
this machine has), lets the two panes hold a short conversation and photographs the page in headless Chrome or Edge
at 1440x900, full page, light and dark: the chat with the panel and "reveal true order" on in V-cloak mode and in
baseline mode, then the dashboard, the experiments, the logs and the architecture view. The PNGs go to
`evidence/screens/` and one row per file to `evidence/INDEX.md`, with the run directory, the commit and the data
state.

- The data state is read from the page. Until M18 the four other views show the bundled sample data, so their rows say
  `seed`: they show the interface, never a result. The chat rows say `measured` because the conversation and the
  stored rows are from a real run of the service; nothing in them is a timing.
- A picture is taken as the page is. The footer reads "dashboard data: seed" until M18 generates the dashboard's
  data; the index row of a chat picture quotes it, and the epoch and backend the strip showed.
- Calling the script again for the same run directory overwrites that run's pictures and replaces their rows. A
  picture of another run is never overwritten: it moves to `evidence/superseded/` first (with the time of its run in
  the name when both runs fall on one day), and the new row says where it is kept.
- If a check fails (the V-cloak order came out monotonic, a pane stopped, the page logged an error) nothing is written
  to `evidence/` and the script exits 1; what it saw is in `capture_evidence.json` of the run directory.

### The strip at the top
From left to right: the open epoch, the window, how many accepted messages wait for the next write against the slots
of an epoch, the store mode, and what computes (`numpy · local` on the laptop: the thread model on the host CPU,
correctness only, never a GPU result; hover for the device).

- The epoch is the server's, not the page's: every second the page asks `GET /v1/stats/live` for the server's clock
  and counts on from that answer until the next one. It never counts from the clock of the browser's machine, so a
  wrong clock there does not show; the error is at most the travel time of one answer.
- When the server stops answering, the strip greys out and shows `—` within three seconds. It does not go on counting.
  The moving clock of the page opened from a file is demo data and the chip at the top right says so.
- In baseline mode there is no epoch, no slot count and no compute backend, because the baseline has none: it stores
  each message as it arrives. With `--compare` the V-cloak scheduler still runs underneath; the strip shows the store
  that answers.
- The fill is almost always `0 / 64` in a demo: an epoch is 200 ms, so a typed message waits for a fraction of a
  second. It is a count at the moment of the answer, not a load figure.
- Not on the strip: the time of the last write. The API gives it with `--dev` (`last_write_ms`), a host wall clock
  on the numpy engine; it is not a performance number and is kept off the screen and out of the pictures.

## 2. The order-recovery attack, live (M18 S4)

Start the app with `python -m vcloak.cli serve --dev --store sqlite`, open **Experiments**, pick a layout and press
**Run attack**. On a first visit the view shows the stored result straight away; a live run starts only from the button.

What the button does: `POST /v1/eval/attack` (dev only, 403 otherwise) replays the M14 seed traffic (seed, number of
conversations and simulated duration are printed in the "This run" panel) through a second service into a new,
empty in-memory store of that layout, dumps the store in physical order and runs the attack of the oracle on the
dump. The page polls `GET /v1/eval/attack` and then shows:

- **The dump**: rows of one visible round in the order the store holds them, each numbered with when it was really
  sent among the rows shown. That order is all the attacker has inside a round.
- **The attacker's guess**: the first 24 turns of the replay, each right (✓) or wrong (✗); underlined when both
  messages fall in one visible round.
- **Turn-order accuracy** over all turns, against the 50 % chance mark, and the comparison with the stored
  `S-TURNACC-<layout>` of `web/data/dashboard.json`: same seed and sizes, so the two must be **identical**, not close.

Say why it is a new store: the store the chat uses cannot be scored, because the server does not know the true
order; that is what it hides. The live run computes on the numpy backend (one thread owns the service's engine,
ADR-015); the stored values came from the GPU runner and are the same on both backends.

Checking it before the review: `python scripts/check_live_attack.py` runs all six layouts through the served endpoint
and fails unless each is identical to the stored value (first run: runs/20261014-102648_M18_s4_live_attack).
Without `--dev` or from `file://`, the view shows the stored value with its provenance and an illustration that says
it is one.

## 3. The project's own logs (M18 S5)

With the same `serve --dev`, open **Logs**. The four tabs are the session log, the audit log, the metrics index and
the issues of `state/`, tailed through `GET /v1/logs?kind=session|audit|metrics|issues&tail=N` (dev only, 403
otherwise). **Follow** re-reads the tail every few seconds; the filter box marks matching lines.

What to say: the route takes one of four names, never a path, and every line passes the server's redaction first
(`src/vcloak/service/logsapi.py`): absolute file paths, e-mail addresses, `name=value` for conversation ids, tokens,
buckets, sequence and row ids, and token-shaped strings are replaced. The line above the log says how many lines of
the tail had something replaced. The redaction is a second layer: the files are written under the secret scan (G4)
and the service's own log goes through the allow-list of `logsafe`.

The proof is `tests/integration/test_logs_api.py`: it drives traffic, writes every value that traffic produced into a
copy of `state/` as a careless log line would, and finds none of them in what is served. How often the token rule
misses a random token is in runs/20261014-105859_M18_s5_checks/redaction_rate.txt.
Without `--dev`, the view says the server does not serve its logs; in the page opened from a file it shows example
lines and says they are examples.

## 4. Where a message goes (M18 S6)
Open **Architecture** and press **Play**. A dot walks the write path S0→S10 and then the read path R1→R5; the box
under the drawing says what each state is and where it lives. Only S9 and S10, drawn dark with "on disk", are
durable: everything before them is on the client, on the network, in host memory or in GPU memory. The dashed line
is where a read starts: from the stored rows.

What to say: the drawing is ai/ARCHITECTURE.md section 2, and its parameters (BLOCK, EPOCH_MS, SLOTS, WINDOW_S,
BUCKETS, CAND_K, the tag size) are read from `src/vcloak/config.py` by `scripts/export_dashboard.py` into the
`architecture` block of `web/data/dashboard.json`, so the page cannot disagree with the code. With a live server the
line above the drawing gives the epoch the scheduler has open and the last one written to the store.

The table below it is the honest part. Its first line is the ADR-031 sentence: V-cloak conceals the order of storage
within a window, and not the access pattern or which rows belong to one conversation. Each row says concealed,
partly visible or visible, why, and, where a measurement exists, the value from the metrics index with its run. The
row "order across windows" carries the turn-order accuracy at W = 60 s: the attack is right on turns that cross a
window and at chance inside one. If a measured value is missing from the index, its cell reads NOT MEASURED.
