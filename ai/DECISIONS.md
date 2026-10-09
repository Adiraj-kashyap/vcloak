# DECISIONS (ADR log) — append only

Format: `## ADR-<n> — <title> — <ACCEPTED|PROPOSED|SUPERSEDED by ADR-m> — <date>` then Context / Decision / Consequences.

## ADR-001 — CUDA through CuPy RawModule — ACCEPTED
Context: must run on a student laptop (Windows or Linux) with minimal build friction.
Decision: kernels are `.cu` files compiled at runtime by NVRTC via CuPy; the same files also compile with nvcc for SASS checks.
Consequences: no CMake or pybind11 build; `nvcc` is only needed for M08.

## ADR-002 — Reference oracle is the correctness ground truth — ACCEPTED
Context: GPU code must be verifiable. Decision: every GPU function has a CPU `*_ref` twin; tests are bit-exact.
Consequences: the oracle is ported and updated to the crypto profile of ADR-003 in M01/M02.

## ADR-003 — GPU-native server crypto profile (ChaCha20 / Poly1305 only) — ACCEPTED
Context: the paper's draft used HKDF, HMAC-SHA256 and AES-GCM for server-side keys. Running those on the
CPU would put K_order in host memory, contradicting "K_order lives only in GPU memory". AES T-table
implementations on GPUs are also exactly what Trident and pacSCA attack.
Decision: all server-side key use runs on the GPU with the ChaCha20 block function (as a PRF and a stream
cipher) plus Poly1305: tags, subkey derivation, bucket PRF, and ChaCha20-Poly1305 for seq_enc (formats in
ARCHITECTURE §5). Client-side content crypto stays X25519 + HKDF-SHA256 + AES-256-GCM.
Consequences: table-free, constant-time-friendly kernels. The paper text (Sec. IV, Table 3, Alg. 1)
must be updated to this profile; M16 flags it.

## ADR-004 — Coarse visible window with re-shuffle — ACCEPTED
Context: E1 on the Review-1 design showed a 98.3% turn-order leak across 200 ms epochs.
Decision: visible round = window W (default 60 s); each closed window is rewritten under a fresh permutation
into a new partition; WAL retention < W. P1 is stated per window.

## ADR-005 — One thread per compare-exchange pair — ACCEPTED
Context: the paper's Listing 1 launches one thread per element; the partner thread performs `x ^= 0` writes
on both elements, which races with the active thread and can write stale values back.
Decision: launch n/2 threads, each owning exactly one pair (i, i+j). No element is written by two threads in a launch.

## ADR-006 — Payload gather on the host — ACCEPTED
Context: gathering payloads by permutation index on the GPU makes addresses depend on the secret permutation.
Decision: the GPU permutes only 24-byte key records; payload reordering happens on the host after D2H.
Consequences: a co-resident observer of host memory could learn the permutation, but that is a live-server
compromise, which is out of scope. Documented in the leakage table.

## ADR-007 — Transient host exposure of K_master at boot — ACCEPTED
Context: the sealed master key must be unsealed with a passphrase (Argon2id KEK).
Decision: unseal on the host into a `bytearray`, copy to VRAM, derive subkeys on the GPU, overwrite the
host buffer immediately. Plaintext keys never touch disk. Documented as a boot-time exposure window.

## ADR-008 — PostgreSQL primary, SQLite for tests — ACCEPTED
Decision: production path uses PostgreSQL 16 (Docker or native) with RANGE partitioning by window.
Unit and CI tests may use SQLite through the same `Repo` protocol. Evaluation numbers (M14, M15) must come from PostgreSQL.
