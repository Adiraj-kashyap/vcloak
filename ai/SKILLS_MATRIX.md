# SKILLS MATRIX

What each module needs to know (for the agent's self-check and for the owner who must present it).
★ = core skill the module cannot be done without.

| Module | Owner | Skills required |
|---|---|---|
| M00 Bootstrap & GPU runner | Aditya | ★Python packaging, ★free cloud GPU runners (Colab/Kaggle), zip job bridge design, NVML, git |
| M01 Oracle port & golden vectors | Abhishek | ★NumPy vectorisation, pytest, JSON test vectors, reading the seed oracle |
| M02 CPU crypto & key lifecycle | Abhishek | ★ChaCha20/Poly1305 (RFC 8439), Argon2id, X25519/HKDF/AES-GCM (`cryptography`), sealed key files |
| M03 GPU bitonic kernel | Aditya | ★Bitonic networks, ★writing a NumPy thread-model twin of a kernel, CUDA thread/block model, shared memory, `__syncthreads`, mask-based swaps, CuPy RawModule |
| M04 GPU ChaCha20 tags | Aditya | ★ChaCha20 quarter-round, 32-bit ARX on GPU, endianness, RFC test vectors |
| M05 GPU AEAD open + restore + compaction | Aditya | ★Poly1305 multi-limb arithmetic, constant-time compare, composite sort keys |
| M06 GPU engine | Aditya | ★Streams, pinned memory, device-resident keys, zeroization, API design |
| M07 GPU performance metrics | Aditya | ★CUDA-event timing, statistics (median/percentiles/CV), NVML, roofline-style bandwidth reasoning, plotting |
| M08 GPU obliviousness audit | Aditya | ★dudect/Welch t-test, Nsight Compute CLI, cuobjdump SASS reading, warp divergence |
| M09 Storage | Divyansh | ★PostgreSQL partitioning, transactions, psycopg 3, MVCC behaviour, Docker |
| M10 Service & scheduler | Divyansh | ★FastAPI, asyncio epoch loop, simulated vs wall clock, backpressure |
| M11 Session security | Divyansh | ★DPoP (RFC 9449), ES256 JWS, JWK thumbprints (RFC 7638), refresh rotation, Argon2id login, log redaction |
| M12 Client SDK & CLI | Abhishek | ★X25519 + HKDF + AES-GCM, fixed-size padding, httpx/websockets |
| M13 Frontend: chat | Abhishek | ★WebCrypto (non-extractable ES256, ECDH+HKDF, AES-GCM), IndexedDB, vanilla ES modules, CSP |
| M18 Frontend: dashboard | Abhishek, Divyansh | ★Hand-written SVG charts, data provenance plumbing, log redaction, accessible UI (keyboard, dark mode, table views) |
| M14 Security evaluation | Abhishek | ★Kendall τ, χ² with permutation correction, attack simulation, anonymity-set analysis |
| M15 End-to-end performance | Divyansh | ★Load generation, latency percentiles, baseline design, GPU utilisation sampling |
| M16 Results export | Abhishek | matplotlib, LaTeX macro generation, reproducible figures |
| M17 Final audit & demo | Team | Reproducibility checks, demo scripting, report writing |

## Remote-GPU skill (applies to M03–M08, and to anyone presenting them)
Know: why an integrated GPU cannot host this threat model (ADR-010); what the `numpy` backend proves and
what it cannot; how a measurement travels from Colab into `runs/` without anyone retyping it; and why
numbers from two runner sessions are never merged into one figure.

## Agent self-check
Before starting a module, confirm you can state (in ≤3 lines, not in chat) the core algorithm of each
★ skill. If a skill involves an external standard (RFC 8439, RFC 9449, RFC 7638), implement against its
published test vectors, which must be copied into `tests/golden/` with the source cited.

## Presenter check (for the human owner)
Each module's `## Presenter notes` section lists 3 questions the panel may ask about it.
The owner should be able to answer them without notes.
