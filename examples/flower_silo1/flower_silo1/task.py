"""NumPy ridge-style local training and parameter hashing."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Sequence

import numpy as np
from flwr.app import ArrayRecord


def _finite(value: float, label: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    return value


def init_parameters(dim: int) -> list[np.ndarray]:
    """Create a zero-initialized weight vector plus bias (length ``dim``)."""
    if dim < 2:
        raise ValueError("parameter dim must include bias (feature count + 1)")
    return [np.zeros((dim,), dtype=np.float64)]


def mse_loss(
    parameters: Sequence[float],
    xs: Sequence[Sequence[float]],
    ys: Sequence[float],
) -> float:
    """Mean squared error for linear model ``y_hat = X @ w + b``."""
    if not xs:
        raise ValueError("no samples for loss")
    dim = len(parameters)
    weights = np.asarray(parameters[: dim - 1], dtype=np.float64)
    bias = float(parameters[dim - 1])
    total = 0.0
    for row, target in zip(xs, ys, strict=True):
        pred = float(np.dot(weights, np.asarray(row, dtype=np.float64)) + bias)
        total += (pred - float(target)) ** 2
    return total / len(xs)


def train_local_ridge(
    initial: Sequence[float],
    xs: Sequence[Sequence[float]],
    ys: Sequence[float],
    *,
    step_size: float,
    l2: float,
    steps: int,
) -> tuple[list[float], float]:
    """Run fixed-step ridge GD from ``initial`` and return parameters and final loss."""
    step = _finite(float(step_size), "step_size")
    reg = _finite(float(l2), "l2")
    if steps < 1:
        raise ValueError("steps must be >= 1")
    dim = len(initial)
    params = [float(v) for v in initial]
    n = len(xs)
    for _ in range(steps):
        grad_w = [0.0] * (dim - 1)
        grad_b = 0.0
        for row, target in zip(xs, ys, strict=True):
            x = np.asarray(row, dtype=np.float64)
            pred = sum(params[i] * float(x[i]) for i in range(dim - 1)) + params[dim - 1]
            err = pred - float(target)
            for i in range(dim - 1):
                grad_w[i] += err * float(x[i])
            grad_b += err
        for i in range(dim - 1):
            params[i] -= step * (grad_w[i] / n + reg * params[i])
        params[dim - 1] -= step * (grad_b / n)
    loss = mse_loss(params, xs, ys)
    return params, loss


def arrays_to_vector(arrays: list[np.ndarray]) -> list[float]:
    """Flatten the single weight vector ArrayRecord used by this example."""
    if len(arrays) != 1:
        raise ValueError("expected one parameter array")
    return [float(x) for x in arrays[0].reshape(-1)]


def vector_to_arrays(params: Sequence[float]) -> list[np.ndarray]:
    """Wrap parameters as a single NumPy vector for ArrayRecord transport."""
    return [np.asarray(params, dtype=np.float64)]


def hash_array_record(record: ArrayRecord) -> str:
    """SHA-256 fingerprint of all arrays in an ArrayRecord (shape, dtype, bytes)."""
    parts: list[bytes] = []
    for arr in record.to_numpy_ndarrays():
        parts.append(
            json.dumps(
                {"shape": list(arr.shape), "dtype": str(arr.dtype)},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        parts.append(arr.tobytes(order="C"))
    return hashlib.sha256(b"".join(parts)).hexdigest()
