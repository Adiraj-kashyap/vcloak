# ARCHITECTURE

## 1. Components
```
[Client A/B] --TLS1.3+DPoP--> [Session gateway] --> [Round scheduler] --> [GpuEngine] --> [PostgreSQL]
                                   |                                   ^   (VRAM keys)      |
                                   +--> [Read handler] --fixed-K fetch-+--------------------+
```
| Component | Package | Owner |
|---|---|---|
| Reference oracle (CPU, tests only) | `vcloak.oracle` | team |
| CPU crypto (client + references) | `vcloak.crypto` | Abhishek |
| CUDA kernels | `kernels/*.cu`, wrappers in `vcloak.gpu.kernels` | Aditya |
| Device key store and engine | `vcloak.gpu.keystore`, `vcloak.gpu.engine` | Aditya |
| Storage | `vcloak.storage` | Divyansh |
| Service (FastAPI, scheduler, session) | `vcloak.service` | Divyansh |
| Client SDK, CLI, web | `vcloak.client`, `web/` | Abhishek |
| Benchmarks and telemetry | `vcloak.bench`, `bench/` | Aditya |
| Evaluation (attacks, statistics) | `vcloak.eval` | Abhishek |

## 2. Data-state flow (must stay true in code)
WRITE: S0 plaintext+seq → S1 padded block (BLOCK) → S2 AES-256-GCM under K_content [client]
→ S3 TLS + DPoP [network] → S4 queued in epoch e [host] → S5 batch padded to SLOTS with dummies
→ S6 128-bit ChaCha20 tags (K_tag, nonce=epoch) [VRAM] → S7 bitonic permute → S8 oblivious compaction
→ S9 row(uuid, bucket, win, seq_enc, payload) [PostgreSQL hot] → S10 window re-shuffled [PostgreSQL cold]

READ: R1 fixed-K candidates for (bucket, win) → R2 GPU AEAD-open of seq_enc (K_seq) → R3 bitonic on
(miss, seq, slot) → R4 ordered ciphertexts over TLS → R5 client decrypt (K_content).

Only S9 and S10 are durable. Neither contains a key, a serial id or a fine timestamp.

## 3. Repository layout (created by the build)
```
vcloak/
├── CLAUDE.md, START_HERE.md, .claude/     (kit — do not delete)
├── ai/, state/, seed/                     (kit — specs, live state, inputs)
├── pyproject.toml, requirements.lock, Makefile (or tasks.py on Windows), docker-compose.yml
├── src/vcloak/
│   ├── config.py
│   ├── oracle/        reference.py  attacks.py  stats.py
│   ├── crypto/        chacha_ref.py  aead_ref.py  keys.py  client.py
│   ├── gpu/           runtime.py  kernels.py  keystore.py  engine.py  telemetry.py
│   ├── storage/       schema.sql  repo.py  reshuffle.py
│   ├── service/       app.py  scheduler.py  session.py  models.py  logsafe.py  baseline.py
│   ├── client/        sdk.py  cli.py
│   ├── bench/         timing.py  baselines.py  report.py
│   └── eval/          traffic.py  attack.py  uniformity.py  anonymity.py
├── kernels/           common.cuh  bitonic.cu  chacha20.cuh  chacha_tags.cu  poly1305.cuh  aead_open.cu  prf.cu
├── tests/             unit/  gpu/  integration/  security/  golden/ (JSON vectors)
├── bench/             run_kernels.py  run_pipeline.py  run_dudect.py  run_ncu.(sh|ps1)  run_e2e.py
├── web/               index.html  app.js  (M13)
├── runs/              raw measurement dirs (gitignored except manifest.json + summary.json)
├── results/           paper-ready tables, figures, macros (committed)
└── docs/              API.md  DEMO.md  REPORT_CH4_NOTES.md
```

## 4. Key interfaces (stable contracts; change only through an ADR)

```python
# vcloak.gpu.keystore
class DeviceKeyStore:
    def load_master(self, master: bytearray) -> None   # copies to VRAM, derives subkeys on GPU, zeroizes `master`
    def zeroize(self) -> None                           # memset device key buffers to 0
    @property
    def ready(self) -> bool

# vcloak.gpu.engine
@dataclass
class Submission:  conv_id: int; seq: int; payload: bytes          # payload = client ciphertext (opaque)
@dataclass
class StoredRow:   row_id: uuid.UUID; bucket: int; win: int; seq_enc: bytes; payload: bytes

class GpuEngine:
    def __init__(self, keys: DeviceKeyStore, slots: int, buckets: int, window_s: int, epoch_ms: int)
    def write_epoch(self, epoch: int, batch: list[Submission]) -> list[StoredRow]   # permuted, dummies stripped
    def reshuffle_window(self, win: int, rows: list[StoredRow]) -> list[StoredRow]  # fresh permutation
    def bucket_of(self, conv_ids: np.ndarray) -> np.ndarray                         # GPU PRF
    def read_window(self, conv_id: int, candidates: list[StoredRow], K: int) -> list[bytes]  # ordered payloads
    def last_timings(self) -> dict[str, float]    # per-stage CUDA-event ms of the last call

# vcloak.storage.repo
class Repo(Protocol):
    def insert_rows(self, rows: list[StoredRow]) -> None
    def fetch_candidates(self, bucket: int, win: int, K: int) -> list[StoredRow]   # exactly K, padded with dummy rows
    def rewrite_window(self, win: int, rows: list[StoredRow]) -> None              # new partition, atomic swap
    def dump(self) -> list[StoredRow]                                              # physical order, for the attack
```

## 5. Byte formats (little-endian unless stated)
- **Tag** for slot i in epoch e: `ks = ChaCha20(K_tag, counter=0, nonce=LE64(e)||00000000)`;
  `hi = LE64(ks[16i:16i+8])`, `lo = LE64(ks[16i+8:16i+16])`.
- **Re-shuffle tag** for window w: same with nonce `LE64(w)||00000080` (domain separation).
- **Bucket**: `LE32(ChaCha20Block(K_bkt, counter=0, nonce=LE64(conv_id)||00000000)[0:4]) mod B`.
- **seq_enc** (44 B): `nonce(12) || ChaCha20-Poly1305(K_seq, nonce, pt=LE64(conv_id)||LE64(seq), aad=b"vcloak-seq-v1")`.
- **Subkeys**: `K_x = ChaCha20Block(K_master, counter=0, nonce=label_x)[0:32]` with labels
  `b"vcloak-tag\0\0"`, `b"vcloak-seq\0\0"`, `b"vcloak-bkt\0\0"` (12 bytes each).
- **Dummy slot**: payload index ≥ n_real; dummy rows in candidate sets carry random 44-byte seq_enc
  that fails authentication, so they are treated as misses.
