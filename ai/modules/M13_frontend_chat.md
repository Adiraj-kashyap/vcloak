# M13 — Frontend part 1: the chat app and the server-view demo
owner: Abhishek · depends_on: M12 · est_sessions: 2 · human_gates: none

## Goal
Turn the shipped `web/` prototype into a live two-user messaging app that also *shows* what the server
stores, with a switch between V-cloak and the unprotected baseline. This is the centrepiece of the demo.

## Required reading
- `ai/FRONTEND.md` (whole) · `ai/ARCHITECTURE.md §4b` · `docs/API.md` · `src/vcloak/client/sdk.py` (signatures)
- `web/js/api.js` and `web/js/chat.js` (the prototype's contracts — read before changing anything)

## Deliverables
`web/` wired to the live API; `src/vcloak/service/web.py` (static mount at `/app`, CSP headers);
`/v1/dump`, `/v1/stats/live` and `/v1/mode` endpoints (dev-gated where noted); `web/js/crypto.js`
(WebCrypto: non-extractable ES256 device key in IndexedDB, ECDH + HKDF + AES-GCM content key);
`tests/integration/test_web_app.py`; `docs/DEMO.md` (chat section);
`scripts/capture_evidence.py` (headless-browser capture of the app views → `evidence/screens/` + INDEX rows).

## Steps
- **S1 Serve it.** Mount `web/` at `/app` with `Cache-Control: no-store` in dev and a strict CSP
  (`default-src 'self'`; no inline script). Check: `GET /app` returns the shell and `pytest` asserts the CSP header.
- **S2 Real sessions.** Replace the prototype's fake login with M11's flow: register/login, a
  non-extractable ES256 key per pane, DPoP headers on every request, refresh rotation. Two panes = two
  independent sessions in one page (separate IndexedDB key handles). Check: both panes authenticate and send.
- **S3 Real messages.** Content encryption in the browser (ECDH P-256 + HKDF → AES-256-GCM, fixed BLOCK padding);
  send to `/v1/messages`, read via `/v1/read`, verify sequence continuity client-side and flag a gap in the UI.
  Check: a 30-message two-user round trip across ≥2 windows is exact in order.
- **S4 Server view.** The panel under the chat shows the stored rows for the current window from `/v1/dump`
  (dev mode only, 403 otherwise), in physical order, with `row_id`, `bucket`, `win`, truncated `seq_enc`,
  truncated `payload`. A "reveal true order" dev toggle overlays each row's real send index, making the shuffle visible.
  Check: the displayed order differs from the send order, and the overlay matches the client's true sequence.
- **S5 Mode switch.** `/v1/mode` (dev) flips between `vcloak` and `baseline`; the server view repaints and a
  caption states what each layout leaks. Check: in baseline the revealed order is monotonic; in V-cloak it is not.
- **S5b Evidence capture script.** `scripts/capture_evidence.py --module <Mxx>`: serve the app locally,
  drive a headless browser (Playwright, or Chrome headless if already present), capture each view at
  1440×900 full-page in **both themes**, plus the chat with the server-view panel in V-cloak mode and in
  baseline mode with "reveal true order" on — that pair is the single most useful image in the whole project.
  Write PNGs to `evidence/screens/` and append rows to `evidence/INDEX.md` with the git sha, the data state
  (`measured`/`seed`/`quick`) and the run dir. Rules in `ai/EVIDENCE.md`.
  Check: running it produces ≥8 PNGs and the same number of index rows; re-running overwrites cleanly.
- **S6 Live strip.** Epoch/window clock, `queued/slots` fill, and backend/runner provenance from `/v1/stats/live`.
  Check: the strip ticks with real epochs and does not drift.

## Audit checklist
- A1 Nothing in the chat path decrypts on the server (test inspects stored payloads: no plaintext).
- A2 The browser's device key cannot be exported (test calls `exportKey` and expects a rejection; recorded in docs/DEMO.md).
- A3 `/v1/dump` and the reveal toggle are hard-disabled without `--dev` (test expects 403).
- A4 The app still loads from `file://` with demo data when the backend is down (manual check, screenshot in runs/).
- A5 CSP present; no inline scripts; no CDN requests (grep the HTML/JS for `http`).
- A6 `capture_evidence.py` runs clean and its index rows carry run dirs and data-state labels.
- G1–G10.

## Presenter notes
1. Show the same conversation in baseline and V-cloak mode, and explain what changed in the stored rows.
2. What exactly is `seq_enc`, and why can the audience not read it?
3. Where does the browser key live, and why can't script steal it?

## Next: M14  (M18 needs M14's results before the dashboard has anything to show)

## Amendments
- 2026-10-12 (session 25, S1-S3): S3 says "ECDH P-256"; the browser uses X25519, the agreement M12 fixed in
  docs/API.md, so that a pane and the Python SDK are one protocol (ADR-020). P-256 is the ES256 device key only.
- The session and conversation logic is `web/js/client.js` (a port of `vcloak.client.sdk`); `web/js/crypto.js` holds
  the WebCrypto and IndexedDB parts. Both are extra classic scripts in `web/index.html`.
- `GET /v1/stats/live` exists from S1 on in a first form (mode, dev, sessions, public parameters and counters,
  payload size), because the page needs it to tell a live server from demo data; `epoch`, `last_write_ms` and `gpu`
  are S6.
- The headless browser is the installed Chrome or Edge driven over the DevTools protocol (`scripts/headless.py`),
  not Playwright: nothing to install or download. `tests/integration/test_web_app.py` and S5b use it.
- The CSP is `default-src 'self'` plus explicit directives; `style-src-attr 'unsafe-inline'` is a relaxation that
  stays until M18 (ISSUE-29). The headers are set by an ASGI middleware, so the redirect of `/app` and a 404 carry
  them too.
- A pane reads once a second on a fixed schedule instead of following the socket ticks (ADR-020 (5)).
- 2026-10-12 (session 26, S4): the panel shows the newest windows, not the current window only, each row marked
  with the state of its window; the open window still lies in epoch order by design, so the S4 check ("the displayed
  order differs from the send order") is made on closed, re-shuffled windows (ADR-021).
- The "reveal true order" overlay is computed in the page from what the panes read and verified (payload bytes
  matched to stored rows), not supplied by the server; `/v1/dump` therefore returns whole `seq_enc` and `payload`
  values (base64) and the page truncates them for display (ADR-021).
- `/v1/dump` takes `limit` and `windows`; it also serves the baseline backend (`state: "arrival"`), ahead of S5.
- `tests/service_contract.py` expected 404 for `/v1/dump` (M10); it now expects the 403 of A3.
