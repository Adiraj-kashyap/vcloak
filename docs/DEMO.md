# Demo guide

How to show V-cloak running. This file grows with the frontend: the chat section is M13 (steps S1-S3 so far);
the server view, the mode switch and the live strip are added by S4-S6, the dashboard by M18.

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

### Not shown yet
The stored rows under the panes, "Reveal true order" and the baseline switch need the dev routes of S4 and S5; until
then the panel says that the server does not hand out its rows, and both switches are disabled on a live server.
