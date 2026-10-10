"""Shared fixtures. Markers `gpu`, `integration` and `slow` are declared in pyproject.toml."""
from __future__ import annotations

import pytest

from vcloak.gpu.runtime import Backend, get_backend


@pytest.fixture(scope="session")
def backend() -> Backend:
    """The backend selected by VCLOAK_BACKEND (numpy on the laptop, cupy on the runner)."""
    return get_backend()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if get_backend("auto").is_gpu:
        return
    skip = pytest.mark.skip(reason="needs a CUDA device: runs on the Colab/Kaggle runner (ai/GPU_RUNNER.md)")
    for item in items:
        if "gpu" in item.keywords:
            item.add_marker(skip)
