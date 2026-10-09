# PROJECT BRIEF — V-cloak

## 1. One-line summary
V-cloak hides the **order** in which encrypted messages were written to a database. It permutes each
batch inside GPU memory before storage, and restores order only through a sequence number
encrypted under a key that never leaves GPU memory.

## 2. Team and context
- Capstone, SCOPE, VIT Chennai. Guide: Dr. Mary Shamala L.
- Aditya Raj (23BCE1052): GPU kernels and profiling.
- Divyansh Patil (23BCE1506): backend, storage and session security.
- Abhishek Singh (23BCE5044): crypto, client and evaluation.
- Review 3 criteria (5 marks each): Implementation (about 50% of scope, executable and attributable),
  Technical accuracy, Results obtained so far, Presentation and clarity.

## 3. Threat model
- **Adversary:** passive; obtains a full snapshot of the persistent store (stolen backup, pg_dump,
  disk image, insider read access). Cannot break ChaCha20, Poly1305, AES-GCM or X25519.
- **Out of scope:** a compromised *running* backend or GPU memory, active/malicious servers,
  network traffic analysis of the client link, TEEs and custom hardware.

## 4. Properties
- **P1, order indistinguishability per window.** For two sequences with the same multiset of
  messages in each visible window W, the dump is computationally indistinguishable.
- **P2, correct restoration.** The authorised recipient obtains the conversation in true order.
- **P3, data-oblivious execution.** The kernels' access trace and running time depend only on public
  sizes (S, K, n), not on content or true order.

## 5. Known leakage (must stay documented; never claim otherwise)
Window ids (coarse order across windows); number of real messages per window; epoch-level order of
the newest data until its window closes; partial conversation identity (shared HMAC-style buckets);
anything a compromised live server sees.

## 6. Keys (see ADR-003 for the GPU-native crypto profile)
| Key | Holder | Use |
|---|---|---|
| `K_content` | the two clients only | X25519 → HKDF-SHA256 → AES-256-GCM message encryption |
| `K_master` | GPU memory (unsealed at boot) | derives the three subkeys below on the GPU |
| `K_tag` | GPU only | ChaCha20 keystream → 128-bit tags per epoch and per window re-shuffle |
| `K_seq` | GPU only | ChaCha20-Poly1305 over (conv_id, seq) → `seq_enc` |
| `K_bkt` | GPU only | ChaCha20 block as a PRF over conv_id → bucket id mod B |
| `KEK` | host, transient during boot | Argon2id(passphrase) → unseals `secrets/kmaster.sealed` |

## 7. Public parameters (defaults in `src/vcloak/config.py`)
| Name | Default | Notes |
|---|---|---|
| `EPOCH_MS` | 200 | wall-clock epochs; never extended |
| `SLOTS` | 64 (dev), 65536 (bench) | fixed per epoch; padded with dummies |
| `WINDOW_S` | 60 | visible round granularity; ablation 1, 10, 60, 300 |
| `BUCKETS` | 64 | bucket = PRF(conv_id) mod B |
| `CAND_K` | 128 | fixed read candidate set; must exceed peak bucket-window occupancy |
| `BLOCK` | 4096 | client padded plaintext size in bytes |
| `TAG_BITS` | 128 | two uint64 limbs, plus slot index as tiebreak |

## 8. Evaluation plan (what the final results must contain)
- **E0** restoration correctness · **E1** order-recovery attack (Kendall τ, turn-order accuracy vs W)
- **E2** permutation uniformity (χ² with the (n−1)/n correction and an ideal-sampler calibration; τ band)
- **E3** access-trace invariance (logical) and GPU timing leakage via dudect (physical)
- **E4** GPU kernel and pipeline performance vs CPU baselines; crossover point; NVML telemetry
- **E5** session-security attack matrix
- **E6** end-to-end latency and throughput vs an unprotected baseline backend at 10, 100 and 1000 users

## 9. Interim reference results (from the CPU oracle — targets to re-verify, NOT results)
Turn-order accuracy: conventional 100%, Review-1 design 98.3%, W=10 s 68.5%, W=60 s 56.0%,
W=300 s 50.7%; χ² p≈0.15; τ band 99.6% inside ±3σ; 60/60 restoration. Every one of these must be
re-measured by this build (on GPU where applicable) before appearing in `results/`.
