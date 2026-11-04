"""Import completed external results without invoking the platform's FedAvg path."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

from fastapi import HTTPException

from config import settings
from models.external_result_schemas import ExternalResultImport
from models.packaging_schemas import ModelEntry, ModelRegisterRequest
from services import model_registry
from services.external_result_format import file_hash, read_bundle


def _store() -> Path:
    return (settings.CONFIG_DIR / "model-artifacts" / "external").resolve()


def _source(bundle_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", bundle_id):
        raise HTTPException(status_code=422, detail="Invalid bundle ID")
    inbox = Path(
        os.getenv("FED_EXTERNAL_RESULTS_DIR")
        or settings.CONFIG_DIR / "external-results" / "inbox"
    ).resolve()
    source = (inbox / bundle_id).resolve()
    if not source.is_relative_to(inbox) or not source.is_dir():
        raise HTTPException(
            status_code=422, detail="Bundle is missing or outside the configured inbox"
        )
    return source


def inspect_result(bundle_id: str) -> dict:
    try:
        manifest, _ = read_bundle(_source(bundle_id))
        return {
            "manifest": manifest,
            "artifact_integrity_verified": True,
            "inference_verified": False,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _snapshot(
    source: Path, manifest: dict, artifacts: dict[str, Path]
) -> tuple[str, Path]:
    identity = file_hash(source / "result.json")
    root = _store()
    root.mkdir(parents=True, exist_ok=True)
    target = root / identity
    if target.resolve() != target:
        raise ValueError("Stored result must not redirect through a symlink")
    if not target.exists():
        with tempfile.TemporaryDirectory(prefix=".external-", dir=root) as temporary:
            stage = Path(temporary) / "bundle"
            stage.mkdir()
            shutil.copyfile(source / "result.json", stage / "result.json")
            for artifact in artifacts.values():
                shutil.copyfile(artifact, stage / artifact.name)
            copied, _ = read_bundle(stage)
            if copied != manifest or file_hash(stage / "result.json") != identity:
                raise ValueError("Bundle changed while being imported")
            stage.rename(target)
    copied, _ = read_bundle(target)
    if copied != manifest or file_hash(target / "result.json") != identity:
        raise ValueError("Stored external result differs from its identity")
    return identity, target


def import_result(request: ExternalResultImport) -> tuple[ModelEntry, bool]:
    try:
        source = _source(request.bundle_id)
        manifest, artifacts = read_bundle(source)
        # Reuse the registry's current single-process transaction boundary.
        with model_registry.REGISTRY_LOCK:
            identity, snapshot = _snapshot(source, manifest, artifacts)
            try:
                existing = model_registry.get_model(request.name, request.version)
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
            else:
                metadata = existing.metadata.get("external_result", {})
                if not isinstance(metadata, dict):
                    metadata = {}
                if (
                    metadata.get("artifact_id") == identity
                    and not existing.metadata.get("archived")
                    and existing.framework == manifest["model"]["framework"]
                    and existing.weights_path
                    == str(snapshot / artifacts["inference"].name)
                    and existing.input_schema == manifest["model"]["input_schema"]
                    and existing.output_schema == manifest["model"]["output_schema"]
                ):
                    return existing, False
                raise HTTPException(
                    status_code=409,
                    detail="Model version already belongs to another result",
                )
            model = manifest["model"]
            metadata = {
                "format": manifest["format"],
                "artifact_id": identity,
                "origin": manifest["origin"],
                "metric_specs": manifest["metric_specs"],
                "artifact_integrity_verified": True,
                "inference_verified": False,
            }
            entry = model_registry.register_model(
                ModelRegisterRequest(
                    name=request.name,
                    version=request.version,
                    framework=model["framework"],
                    weights_path=str(snapshot / artifacts["inference"].name),
                    input_schema=model["input_schema"],
                    output_schema=model["output_schema"],
                    metadata={"external_result": metadata},
                )
            )
            return entry, True
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail="External result storage failed"
        ) from exc


def get_result(name: str, version: str) -> dict:
    entry = model_registry.get_model(name, version)
    metadata = entry.metadata.get("external_result", {})
    if not isinstance(metadata, dict):
        metadata = {}
    identity = metadata.get("artifact_id", "")
    if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{64}", identity):
        raise HTTPException(status_code=404, detail="Model has no external result")
    directory = _store() / identity
    try:
        if directory.resolve() != directory:
            raise ValueError("Stored result must not redirect through a symlink")
        manifest, _ = read_bundle(directory)
        if file_hash(directory / "result.json") != identity:
            raise ValueError("Stored result identity mismatch")
        return manifest
    except ValueError as exc:
        raise HTTPException(
            status_code=409, detail="Stored external result failed integrity checks"
        ) from exc
