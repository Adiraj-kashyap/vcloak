# TESTING

## 1. Layers
| Layer | Path | Runs on | Purpose |
|---|---|---|---|
| unit | `tests/unit/` | CPU | pure functions, formats, config, oracle |
| golden | `tests/golden/*.json` | data | RFC and oracle vectors (cited sources) |
| gpu | `tests/gpu/` | GPU | bit-exact kernels vs CPU references; marked `@pytest.mark.gpu` |
| integration | `tests/integration/` | GPU + DB | engine + storage + service round-trips |
| security | `tests/security/` | CPU/GPU | session attack matrix, log redaction, secrets checks |
| frontend | `tests/integration/test_web_*.py` | CPU | served shell, CSP, dev-gating of `/v1/dump`, dashboard JSON schema, no literals in `web/js` |

`pytest -m "not gpu"` must pass on the laptop with no GPU (backend `numpy`); `pytest -m gpu` runs only inside a
GPU job on the runner, where `gpu_entry.py` executes it with `VCLOAK_BACKEND=cupy`.
`conftest.py` skips GPU tests with a clear reason when no device is present (a skip is never a pass: a GPU
module's audit fails G1 until the ingested bundle shows those tests passing on the runner).

## 2. Golden vectors (commit them; cite their source inside the JSON)
- ChaCha20 block function and keystream: RFC 8439 §2.3.2 and §2.4.2.
- Poly1305: RFC 8439 §2.5.2. AEAD ChaCha20-Poly1305: RFC 8439 §2.8.2.
- JWK thumbprint: RFC 7638 §3.1 example.
- Oracle vectors produced in M01: permutation outputs for fixed test keys and epochs at n ∈ {64, 1024, 65536}.

## 2b. Simulator parity (local ↔ GPU)
Every kernel has a NumPy twin in `src/vcloak/gpu/sim.py`. Local tests run the twin; the GPU job runs both and
asserts byte equality. A parity failure is a bug in one of them and blocks the module.

## 3. Bit-exact GPU tests (G5)
For each GPU function f_gpu with a reference f_ref: sizes {2^6, 2^10, 2^16} plus max_log2n in full mode;
seeds {1, 2, 3}; include adversarial inputs (all-equal, sorted, reverse, two-value). Assert byte equality.

## 4. Acceptance gates used by modules
- **Correctness:** 100% equality on all bit-exact tests; restoration exact for every conversation tested.
- **Uniformity (E2):** corrected χ² p-value > 0.01 AND within the range of the ideal-sampler
  calibration; τ-band coverage within binomial 99% bounds of 99.73%.
- **Obliviousness (E3):** identical comparator trace hashes; dudect |t| < 4.5; ncu 0 divergent branches (or NOT_MEASURED with a reason).
- **Real-time:** write_epoch p99 < EPOCH_MS at the configured SLOTS (record the result either way; a miss becomes an issue, not a hidden fact).
