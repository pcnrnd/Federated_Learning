"""사일로 안의 입력/성공 출력 스냅샷. 중앙으로 반환하는 것은 해시와 통계뿐이다."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Callable

from . import synthetic
from .cleaning import apply_recipe
from .integration import load_sources, schema_fingerprint


def encoded(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def output_path(data_dir: str, identity: str) -> Path:
    if len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
        raise ValueError("출력 식별자는 sha256이어야 합니다")
    return Path(data_dir) / ".cleaned" / identity


def execute(data_dir: str, silo_id: str, job: dict, shard: dict, recipe: dict,
            progress: Callable[[int, int, str], None] | None = None) -> dict:
    identity = digest(encoded([job["job_id"], job.get("generation", 0),
                               shard["shard_index"], silo_id, shard["attempt_id"]]))
    destination = output_path(data_dir, identity)
    manifest_path = destination / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_bytes())
        load_output(data_dir, manifest)
        return manifest  # 성공 스냅샷 재사용. 원천을 다시 정제하지 않는다.
    destination.mkdir(parents=True, exist_ok=True)
    # 같은 attempt 권한이 재전송되더라도 로컬 실행자는 하나뿐이다.
    # 중단된 attempt는 중앙 deadline/retry로 새 ID를 받으며 이 원본을 덮지 않는다.
    lock = os.open(destination / "execution.lock", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(lock)
    inputs_dir = destination / "inputs"
    inputs_dir.mkdir(exist_ok=True)
    if recipe.get("mapping"):
        original = {name: Path(data_dir) / filename for name, filename in synthetic.SOURCE_FILES.items()}
    else:
        label = job["dataset_label"]
        if Path(label).name != label or label in (".", ".."):
            raise ValueError("로컬 데이터셋 이름이 유효하지 않습니다")
        path = next((Path(data_dir) / f"{label}{suffix}" for suffix in (".csv", ".json")
                     if (Path(data_dir) / f"{label}{suffix}").is_file()), None)
        if path is None:
            raise FileNotFoundError("지정한 사일로 로컬 데이터셋이 없습니다")
        original = {"rows": path}
    # 실행용 읽기는 fixture 생성과 분리. 부분 원천을 만들거나 덮어쓰지 않는다.
    contents = {name: path.read_bytes() for name, path in original.items()}
    hashes = {name: digest(content) for name, content in contents.items()}
    if any(digest(path.read_bytes()) != hashes[name] for name, path in original.items()):
        raise OSError("입력 스냅샷 중 원천 변경 감지")
    frozen = {}
    for name, content in contents.items():
        frozen[name] = inputs_dir / original[name].name
        frozen[name].write_bytes(content)
    tables = load_sources(frozen)
    rows_in = sum(len(rows) for rows in tables.values())
    data = tables if recipe.get("mapping") else tables["rows"]
    cleaned, counters = apply_recipe(data, recipe["steps"], mapping=recipe.get("mapping"),
        partitions=job.get("partitions", 4), parallelism=job.get("parallelism", 2), on_progress=progress)
    output = encoded(cleaned)
    manifest = {"output_id": identity, "output_hash": digest(output),
        "source_hash": digest(encoded(hashes)), "recipe_hash": digest(encoded(recipe)),
        "schema_fingerprint": schema_fingerprint(cleaned), "rows_in": rows_in,
        "rows_out": len(cleaned), "step_counters": counters, "job_id": job["job_id"],
        "generation": job.get("generation", 0), "attempt_id": shard["attempt_id"], "silo_id": silo_id,
        "source_files": hashes, "partitions": job.get("partitions", 4),
        "parallelism": job.get("parallelism", 2),
        "source_names": {name: path.name for name, path in original.items()},
        "columns": list(cleaned[0]) if cleaned else [],
        "recipe_name": job.get("recipe_name"), "recipe_version": job.get("recipe_version")}
    (destination / "recipe.json").write_bytes(encoded(recipe))
    (destination / "rows.json").write_bytes(output)
    temporary = destination / "manifest.pending"
    temporary.write_bytes(encoded(manifest))
    os.replace(temporary, manifest_path)  # 성공 marker는 전체 출력 저장 뒤 원자적으로 보인다.
    return manifest


def load_output(data_dir: str, expected: dict) -> tuple[list[dict], dict]:
    destination = output_path(data_dir, expected["output_id"])
    manifest = json.loads((destination / "manifest.json").read_bytes())
    for field in ("output_id", "output_hash", "source_hash", "recipe_hash", "schema_fingerprint"):
        if manifest.get(field) != expected.get(field):
            raise ValueError(f"정제 출력 {field} 불일치")
    for field in ("attempt_id", "rows_in", "rows_out", "generation"):
        if field in expected and manifest.get(field) != expected[field]:
            raise ValueError(f"정제 출력 {field} 불일치")
    content = (destination / "rows.json").read_bytes()
    if digest((destination / "recipe.json").read_bytes()) != manifest["recipe_hash"]:
        raise ValueError("보존 recipe hash 불일치")
    if digest(encoded(manifest["source_files"])) != manifest["source_hash"]:
        raise ValueError("보존 source manifest hash 불일치")
    for name, filename in manifest["source_names"].items():
        if Path(filename).name != filename or digest((destination / "inputs" / filename).read_bytes()) != manifest["source_files"][name]:
            raise ValueError("보존 input hash 불일치")
    if digest(content) != manifest["output_hash"]:
        raise ValueError("보존 출력 hash 불일치")
    rows = json.loads(content)
    if len(rows) != manifest["rows_out"] or schema_fingerprint(rows) != manifest["schema_fingerprint"]:
        raise ValueError("보존 출력 행 수/스키마 불일치")
    return rows, manifest
