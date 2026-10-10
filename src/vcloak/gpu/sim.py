"""Simulator registry: kernel name -> NumPy twin (ai/GPU_GUIDE.md §2).

Each CUDA kernel added to `kernels/` gets a NumPy function here (or registered from its own module)
that takes the same arguments and computes the same thread-indexed arithmetic over
`t = arange(nthreads)`. The twins give correctness on a GPU-less laptop; they say nothing about speed.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

_REGISTRY: dict[str, Callable[..., Any]] = {}


def register(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: register `fn` as the NumPy twin of the CUDA kernel `name`."""

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        if name in _REGISTRY and _REGISTRY[name] is not fn:
            raise ValueError(f"simulator twin {name!r} is already registered")
        _REGISTRY[name] = fn
        return fn

    return deco


def get(name: str) -> Callable[..., Any]:
    """Return the NumPy twin of kernel `name`."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"no simulator twin registered for kernel {name!r}; known: {names()}") from None


def names() -> list[str]:
    """Registered kernel names, sorted."""
    return sorted(_REGISTRY)


@register("vector_add")
def vector_add(a: np.ndarray, b: np.ndarray, out: np.ndarray, n: int) -> None:
    """Twin of the M00 probe kernel: out[t] = a[t] + b[t] for thread ids t < n (uint32 wraparound)."""
    t = np.arange(n)
    out[t] = a[t] + b[t]
