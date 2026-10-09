# STATE — single source of progress (agent-maintained)

```yaml
project: v-cloak
kit_version: 1.0
last_session: 0
last_session_date: null
current_module: M00
current_step: S1
status: NOT_STARTED        # NOT_STARTED | IN_PROGRESS | AUDIT_PENDING | AUDIT_FAILED | DONE | BLOCKED_HUMAN | BLOCKED_TECH
next_unit: M00
last_checkpoint: null
quick_mode_default: false
env:                        # filled by M00 S7
  os: unknown
  wsl: unknown
  python: unknown
  gpu: unknown
  compute_capability: unknown
  vram_gb: unknown
  driver: unknown
  cuda: unknown
  cupy: unknown
  nvcc: unknown
  ncu: unknown
  ncu_counters_permitted: unknown
  max_log2n: unknown
  peak_bw_gbs: unknown
  postgres: unknown
```

## Modules

| ID | Title | Owner | Depends on | Optional | Status | Step | Sessions |
|---|---|---|---|---|---|---|---|
| M00 | Bootstrap & GPU probe | Aditya | — | no | NOT_STARTED | S1 | 0 |
| M01 | Oracle port & golden vectors | Abhishek | M00 | no | NOT_STARTED | S1 | 0 |
| M02 | CPU crypto & key lifecycle | Abhishek | M01 | no | NOT_STARTED | S1 | 0 |
| M03 | GPU bitonic kernel | Aditya | M01 | no | NOT_STARTED | S1 | 0 |
| M04 | GPU ChaCha20 tags/PRF | Aditya | M02, M03 | no | NOT_STARTED | S1 | 0 |
| M05 | GPU AEAD-open, restore, compaction | Aditya | M04 | no | NOT_STARTED | S1 | 0 |
| M06 | GPU engine | Aditya | M05 | no | NOT_STARTED | S1 | 0 |
| M07 | GPU performance metrics (E4) | Aditya | M06 | no | NOT_STARTED | S1 | 0 |
| M08 | GPU obliviousness audit (E3) | Aditya | M06 | no | NOT_STARTED | S1 | 0 |
| M09 | Storage (PostgreSQL) | Divyansh | M06 | no | NOT_STARTED | S1 | 0 |
| M10 | Service & scheduler | Divyansh | M09 | no | NOT_STARTED | S1 | 0 |
| M11 | Session security (E5) | Divyansh | M10 | no | NOT_STARTED | S1 | 0 |
| M12 | Client SDK & CLI | Abhishek | M11 | no | NOT_STARTED | S1 | 0 |
| M13 | Web client | Abhishek | M12 | yes | NOT_STARTED | S1 | 0 |
| M14 | Security evaluation (E0–E2, anon set) | Abhishek | M08, M10 | no | NOT_STARTED | S1 | 0 |
| M15 | End-to-end performance (E6) | Divyansh | M10, M11 | no | NOT_STARTED | S1 | 0 |
| M16 | Results export | Abhishek | M07, M08, M14 | no | NOT_STARTED | S1 | 0 |
| M17 | Final audit & demo | Team | all required | no | NOT_STARTED | S1 | 0 |

## Notes for the agent
- Update the yaml block and the module row together. Keep this file under 120 lines.
- `sessions` counts sessions spent on the module (including audit-only sessions).
