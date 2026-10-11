"""The engine tests reuse the fixtures and window generators of tests/gpu."""
from __future__ import annotations

import sys
from pathlib import Path

GPU_TESTS = str(Path(__file__).resolve().parents[1] / "gpu")
if GPU_TESTS not in sys.path:
    sys.path.insert(0, GPU_TESTS)
