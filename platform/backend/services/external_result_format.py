"""Versioned, engine-independent result bundles. Never imports or executes models."""

from __future__ import annotations

import hashlib
import json
import math
import re
import zipfile
from pathlib import Path

import numpy as np

FORMAT = "federated-result-v1"
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
MAX_ARRAY_BYTES = 512 * 1024 * 1024
MAX_TENSORS = 4096


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite_json(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number")
    return number


def _no_constant(value: str):
    raise ValueError(f"Non-finite JSON constant: {value}")


def _object(value):
    if not isinstance(value, dict):
        raise ValueError("Expected an object")
    return value


def _metrics(manifest: dict) -> None:
    origin = _object(manifest["origin"])
    if (
        not isinstance(origin.get("engine"), str)
        or not 1 <= len(origin["engine"]) <= 128
    ):
        raise ValueError("Missing engine identity")
    result = _object(manifest["result"])
    _object(result["config"])
    rows, specs = result["history"], _object(manifest["metric_specs"])
    if not isinstance(rows, list) or not 1 <= len(rows) <= 10001 or not specs:
        raise ValueError("Missing or oversized history/metric definitions")
    for name, spec in specs.items():
        if not isinstance(name, str) or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_.-]{0,127}", name
        ):
            raise ValueError("Invalid metric name")
        spec = _object(spec)
        if not isinstance(spec.get("unit"), str) or not 1 <= len(spec["unit"]) <= 64:
            raise ValueError("Missing metric unit")
        if type(spec.get("higher_is_better")) is not bool:
            raise ValueError("Missing metric direction")
        if "range" in spec:
            bounds = spec["range"]
            if (
                not isinstance(bounds, list)
                or len(bounds) != 2
                or any(
                    type(x) not in (int, float) or not math.isfinite(x) for x in bounds
                )
                or bounds[0] > bounds[1]
            ):
                raise ValueError("Invalid metric range")
    previous, observed = -1, set()
    for row in rows:
        row = _object(row)
        number = row.get("round")
        if type(number) is not int or number <= previous:
            raise ValueError("Rounds must be nonnegative and strictly increasing")
        previous = number
        for key, value in row.items():
            if key == "round" or value is None:
                continue
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("History values must be finite scalars or null")
            if key in specs:
                observed.add(key)
                if (
                    "range" in specs[key]
                    and not specs[key]["range"][0] <= value <= specs[key]["range"][1]
                ):
                    raise ValueError("Metric outside declared range")
    if observed != set(specs):
        raise ValueError("Metric definition has no observed value")


def _artifact(root: Path, item: dict) -> Path:
    item = _object(item)
    name, expected = item["path"], item["sha256"]
    if (
        not isinstance(name, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name)
        or name == "result.json"
        or not isinstance(expected, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected)
    ):
        raise ValueError("Invalid artifact path or hash")
    path = (root / name).resolve()
    if (
        not path.is_relative_to(root)
        or not path.is_file()
        or not 0 < path.stat().st_size <= MAX_ARTIFACT_BYTES
    ):
        raise ValueError("Artifact outside bundle, missing or oversized")
    if file_hash(path) != expected:
        raise ValueError("Artifact checksum mismatch")
    return path


def _arrays(path: Path, schema: dict) -> None:
    if not 1 <= len(schema) <= MAX_TENSORS:
        raise ValueError("Missing or oversized tensor schema")
    total = 0
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if (
            len(infos) != len(schema)
            or len({x.filename for x in infos}) != len(infos)
            or {x.filename for x in infos} != {key + ".npy" for key in schema}
            or sum(x.file_size for x in infos) > MAX_ARRAY_BYTES + MAX_TENSORS * 10000
        ):
            raise ValueError("Invalid or oversized numeric archive")
        for key, desc in schema.items():
            if not isinstance(key, str) or not re.fullmatch(
                r"[A-Za-z0-9_.-]{1,256}", key
            ):
                raise ValueError("Invalid tensor name")
            desc = _object(desc)
            shape, dtype = desc["shape"], np.dtype(desc["dtype"])
            if (
                not isinstance(shape, list)
                or len(shape) > 32
                or any(type(x) is not int or x <= 0 for x in shape)
                or dtype.kind not in "biuf"
                or dtype.str != desc["dtype"]
            ):
                raise ValueError("Invalid tensor shape or dtype")
            size = math.prod(shape) * dtype.itemsize
            total += size
            if total > MAX_ARRAY_BYTES:
                raise ValueError("Tensor data exceeds interchange limit")
            with archive.open(key + ".npy") as stream:
                version = np.lib.format.read_magic(stream)
                if version == (1, 0):
                    actual_shape, _, actual_dtype = np.lib.format.read_array_header_1_0(
                        stream
                    )
                elif version == (2, 0):
                    actual_shape, _, actual_dtype = np.lib.format.read_array_header_2_0(
                        stream
                    )
                else:
                    raise ValueError("Unsupported numeric array version")
                if (
                    list(actual_shape) != shape
                    or actual_dtype != dtype
                    or stream.tell() + size != archive.getinfo(key + ".npy").file_size
                ):
                    raise ValueError("Tensor header differs from schema")
    with np.load(path, allow_pickle=False) as arrays:
        if any(not np.isfinite(arrays[key]).all() for key in schema):
            raise ValueError("Non-finite tensor")


def read_bundle(directory: Path) -> tuple[dict, dict[str, Path]]:
    """Validate integrity and numeric weights; TorchScript is treated as opaque data."""
    root = Path(directory).resolve()
    manifest_path = root / "result.json"
    try:
        if (
            not manifest_path.resolve().is_relative_to(root)
            or manifest_path.stat().st_size > MAX_MANIFEST_BYTES
        ):
            raise ValueError("Manifest outside bundle or exceeds 4 MiB")
        manifest = _object(
            json.loads(
                manifest_path.read_text(encoding="utf-8"),
                parse_float=_finite_json,
                parse_constant=_no_constant,
            )
        )
        if manifest.get("format") != FORMAT:
            raise ValueError("Unsupported result format")
        _metrics(manifest)
        model = _object(manifest["model"])
        if (
            model.get("framework") != "pytorch"
            or model.get("inference_format") != "torchscript"
        ):
            raise ValueError(
                "This version supports the PyTorch/TorchScript profile only"
            )
        _object(model["input_schema"])
        _object(model["output_schema"])
        artifacts = {
            key: _artifact(root, manifest["artifacts"][key])
            for key in ("weights", "inference")
        }
        if artifacts["weights"] == artifacts["inference"]:
            raise ValueError("Artifact paths must be distinct")
        _arrays(artifacts["weights"], _object(model["tensors"]))
        return manifest, artifacts
    except (
        OSError,
        KeyError,
        TypeError,
        OverflowError,
        EOFError,
        RuntimeError,
        zipfile.BadZipFile,
    ) as exc:
        raise ValueError("Malformed or unreadable result bundle") from exc
