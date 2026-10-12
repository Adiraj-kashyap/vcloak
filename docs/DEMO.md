# Demo guide

How to show V-cloak running. This file grows with the frontend: the chat section is M13 (steps S1-S4 so far);
the mode switch and the live strip are added by S5-S6, the dashboard by M18.

## 1. The chat

### Start
```
python -m vcloak.cli serve --dev --sessions --store sqlite
```
then open `http://127.0.0.1:8000/app/` in Chrome or Edge. `--store sqlite` needs no database; leave it out to use
PostgreSQL (`docker compose up -d --wait db` first). `--dev` uses the public development key: a demo database only.
Use `127.0.0.1` or `localhost`: WebCrypto exists only in a secure context, and plain http counts as one on loopback
only. The chip at the top right must read **live · dev**.

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

### Not shown yet
The baseline switch needs the dev route of S5 and stays disabled on a live server; the strip at the top shows the
window and the queue but not yet the epoch or the compute backend (S6).
