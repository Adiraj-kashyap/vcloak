# TESTING

## 1. Layers
| Layer | Path | Runs on | Purpose |
|---|---|---|---|
| unit | `tests/unit/` | CPU | pure functions, formats, config, oracle |
| golden | `tests/golden/*.json` | data | RFC and oracle vectors (cited sources) |
| gpu | `tests/gpu/` | GPU | bit-exact kernels vs CPU references; marked `@pytest.mark.gpu` |
| integration | `tests/integration/` | GPU + DB | engine + storage + service round-trips |
| security | `tests/security/` | CPU/GPU | session attack matrix, log redaction, secrets checks |

`pytest -m "not gpu"` must pass on any machine; `pytest -m gpu` needs the GPU.
`conftest.py` skips GPU tests with a clear reason if CuPy has no device (but audits then FAIL G1 for
GPU modules; a skip is not a pass).

## 2. Golden vectors (commit them; cite their source inside the JSON)
- ChaCha20 block function and keystream: RFC 8439 §2.3.2 and §2.4.2.
- Poly1305: RFC 8439 §2.5.2. AEAD ChaCha20-Poly1305: RFC 8439 §2.8.2.
- JWK thumbprint: RFC 7638 §3.1 example.
- Oracle vectors produced in M01: permutation outputs for fixed test keys and epochs at n ∈ {64, 1024, 65536}.

## 3. Bit-exact GPU tests (G5)
For each GPU function f_gpu with a reference f_ref: sizes {2^6, 2^10, 2^16} plus max_log2n in full mode;
seeds {1, 2, 3}; include adversarial inputs (all-equal, sorted, reverse, two-value). Assert byte equality.

## 4. Acceptance gates used by modules
- **Correctness:** 100% equality on all bit-exact tests; restoration exact for every conversation tested.
- **Uniformity (E2):** corrected χ² p-value > 0.01 AND within the range of the ideal-sampler
  calibration; τ-band coverage within binomial 99% bounds of 99.73%.
- **Obliviousness (E3):** identical comparator trace hashes; dudect |t| < 4.5; ncu 0 divergent branches (or NOT_MEASURED with a reason).
- **Real-time:** write_epoch p99 < EPOCH_MS at the configured SLOTS (record the result either way; a miss becomes an issue, not a hidden fact).
