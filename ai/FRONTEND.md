# FRONTEND — the V-cloak app (chat + evidence dashboard)

A working prototype already ships in `web/`. **Do not rebuild it from scratch**: wire it to real endpoints,
replace demo data with generated data, and extend it. It is the review demo *and* the product.

## 1. Stack rules (ADR-012)
- Vanilla JS in **classic `<script>` tags** (not ES modules), hand-written SVG charts, one CSS file.
  **No React, no bundler, no CDN, no npm.**
- **Why classic scripts:** browsers block `type="module"` and `fetch()` of local files under `file://`
  (CORS). The offline fallback therefore ships demo data as `web/data/demo-data.js`, which assigns
  `window.VCLOAK_DEMO`, instead of a JSON file that would have to be fetched. Live data is fetched from
  the API only when the page is served over http. Keep it that way, or the review fallback breaks.
- It must open two ways: served at `/app` by FastAPI (live), and straight from `file://` (demo data).
  The review demo depends on the second working when Wi-Fi or the backend does not.
- Mobile-first-safe: a single column below 900 px, no horizontal page scroll, 16 px side gutters.
- Light and dark are both designed; the toggle sets `data-theme` on `<html>` and persists in `localStorage`.
- Every view works with the keyboard; focus rings are never removed; charts have a table view.

## 2. Views
| View | Purpose | Data |
|---|---|---|
| **Chat** | Two users messaging for real, side by side, with a "what the server stores" panel underneath | `/v1/messages`, `/v1/read`, `/v1/dump` (dev) |
| **Dashboard** | Headline tiles + charts: attack results, uniformity, GPU performance, session matrix | `/v1/dashboard` → `web/data/dashboard.json` |
| **Experiments** | Run an experiment and watch it: the order-recovery attack live, window ablation, before/after | `/v1/eval/*` (M18 adds them) or the last stored results |
| **Logs** | Session log, audit log, metrics index, issues — the project's own evidence trail, tailed live | `/v1/logs?kind=…` |
| **Architecture** | The data-state flow S0→S10 / R1→R5, animated as a message moves through it | static + `/v1/stats/live` |

## 3. The chat view is the proof, not a toy
- Two panes (User A, User B) each with their own key pair and session; messages are encrypted in the
  browser/client, never by the server.
- Under the panes, a **server view** shows the actual stored rows for the current window: `row_id` (UUID),
  `bucket`, `win`, `seq_enc`, `payload` — in **physical order**, so the audience can see that the order on
  screen is not the order of sending. A "reveal true order" toggle (dev only) overlays the real sequence
  so the shuffle is visible.
- A mode switch flips the backend between **V-cloak** and **baseline** (M10's unprotected mode) so the
  same conversation can be dumped both ways. This is the single most convincing thing in the demo.
- Show the epoch/window clock ticking, with the current epoch's fill (`queued / slots`).

## 4. Dashboard rules
- Tiles and charts come only from `web/data/dashboard.json` (ADR-013). Each carries its METRIC-ID,
  run directory, and `backend`/`runner` provenance, shown in a provenance line under the chart.
- A metric that is missing renders a `NOT MEASURED` card stating what to run to get it. Never blank, never a guess.
- Quick-mode metrics render with a visible `QUICK` chip and are excluded from any headline tile.
- A banner at the top of the dashboard states the provenance of the newest GPU run: GPU model, runner,
  session, date. If the data is older than the last ingest, say so.

## 5. Chart rules (follow these exactly)
- **Form first:** magnitude → bars; change over n → line (log x and y for the kernel sweep); distribution
  → histogram; one headline number → a stat tile, not a chart. A pie chart is never correct here.
- **One y-axis per chart.** Two different units → two charts.
- Palette (validated for colour-blind separation in both modes — do not substitute hues):
  | Slot | Light | Dark | Used for |
  |---|---|---|---|
  | 1 | `#2a78d6` | `#3987e5` | V-cloak / primary series |
  | 2 | `#eb6834` | `#d95926` | baseline / comparison series |
  | 3 | `#1baf7a` | `#199e70` | third series (e.g. predicted) |
  | 4 | `#eda100` | `#c98500` | fourth series — avoid beside slot 2 |
  Status: good `#0ca30c`, warning `#fab219`, critical `#d03b3b` — always with an icon **and** a label, never colour alone.
  Ink: primary `#0b0b0b`/`#f0efec`, secondary `#52514e`/`#c3c2b7`, muted `#898781`, grid `#e1e0d9`/`#2c2c2a`,
  surface `#fcfcfb`/`#1a1a19`.
- Marks: 2 px lines, ≥8 px markers, 4 px rounded bar ends at the baseline, 2 px gap between adjacent fills,
  recessive grid, no value label on every point — label the endpoints and extremes.
- ≥2 series ⇒ a legend is always present, and ≤4 series are also directly labelled; identity is never colour alone.
- Every chart has: a hover tooltip, a reference line where one exists (chance = 50%, |t| = 4.5, epoch budget),
  and a "Table" toggle that shows the same numbers as text.
- Numbers in tiles use `font-variant-numeric: tabular-nums`; axis ticks too.

## 6. Accuracy rules (these are audited)
- Never render a conclusion the data does not support. "Turn-order accuracy 50.7%" is a measurement;
  "V-cloak is unbreakable" is not, and must not appear anywhere in the UI.
- Label the leakage the system still has (window ids, per-window volume) on the dashboard, not only in the paper.
- If the GPU numbers came from a shared cloud runner, the provenance line says so.
