"""Public parameters (ai/PROJECT_BRIEF.md §7). Constants only: nothing here is secret or mutable."""
from __future__ import annotations

# Epochs and batching
EPOCH_MS: int = 200  # wall-clock epoch length; never extended
SLOTS_DEV: int = 64  # slots per epoch in development
SLOTS_BENCH: int = 65536  # slots per epoch in benchmarks
SLOTS: int = SLOTS_DEV  # fixed per epoch; padded with dummies

# Visible round granularity
WINDOW_S: int = 60
WINDOW_S_ABLATION: tuple[int, ...] = (1, 10, 60, 300)

# Read path
BUCKETS: int = 64  # bucket = PRF(conv_id) mod BUCKETS
CAND_K: int = 128  # fixed read candidate set; must exceed peak bucket-window occupancy

# Record format
BLOCK: int = 4096  # client padded plaintext size in bytes
TAG_BITS: int = 128  # two uint64 limbs, plus slot index as tiebreak

# VRAM budget (ai/GPU_GUIDE.md §8)
ROW_BYTES: int = 48  # device bytes per element, before double buffering
VRAM_FRACTION: float = 0.5  # double buffering: only half of free VRAM is usable
MAX_LOG2N_CAP: int = 24
SWEEP_LOG2N_CAP: int = 22  # keeps one job inside a runner session's time budget

# Timing methodology (ai/GPU_GUIDE.md §4)
TIMING_WARMUP: int = 10
TIMING_RUNS: int = 50
TIMING_RUNS_QUICK: int = 15
TIMING_RUNS_MIN: int = 30

BACKENDS: tuple[str, ...] = ("auto", "cupy", "numpy")


def max_log2n(free_vram_bytes: int) -> int:
    """Largest log2(n) that fits in free VRAM with double buffering, capped at MAX_LOG2N_CAP."""
    rows = int(VRAM_FRACTION * free_vram_bytes) // ROW_BYTES
    if rows < 1:
        return 0
    return min(rows.bit_length() - 1, MAX_LOG2N_CAP)
