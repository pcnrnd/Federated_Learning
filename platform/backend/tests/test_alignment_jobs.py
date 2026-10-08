"""사일로 간 수직 정렬 작업 — 서버는 HMAC 다이제스트만 받아 교집합을 돌려준다 (F4)"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from models.alignment_schemas import AlignmentJobCreate, AlignmentReport, AlignmentSubmit
from services import alignment_service
from silo_sdk import apply_recipe, synthetic
from silo_sdk.alignment import align_rows, hash_ids

KEY = b"silo-shared-align-key-for-tests"
H = [f"{i:064x}" for i in range(6)]


def _create(silos=("silo-4", "silo-5")) -> None:
    alignment_service.create_alignment(
        AlignmentJobCreate(alignment_id="a1", silo_ids=list(silos))
    )


def _submit(silo_id: str, hashes: list[str]) -> None:
    alignment_service.submit_hashes("a1", AlignmentSubmit(silo_id=silo_id, hashed_keys=hashes))


@pytest.mark.unit
def test_create_requires_two_distinct_silos():
    with pytest.raises(ValidationError):
        AlignmentJobCreate(alignment_id="a1", silo_ids=["silo-4"])
    with pytest.raises(ValidationError):
        AlignmentJobCreate(alignment_id="a1", silo_ids=["silo-4", "silo-4"])
    _create()
    with pytest.raises(HTTPException) as exc:
        _create()
    assert exc.value.status_code == 409


@pytest.mark.unit
def test_submit_accepts_only_sha256_hex_digests():
    with pytest.raises(ValidationError):
        AlignmentSubmit(silo_id="silo-4", hashed_keys=["E00412"])  # 원본 id는 거부


@pytest.mark.unit
def test_submit_rules_and_intersection():
    _create()
    with pytest.raises(HTTPException) as exc:
        _submit("silo-9", H[:2])
    assert exc.value.status_code == 403

    _submit("silo-4", [H[3], H[0], H[1], H[2]])
    with pytest.raises(HTTPException) as exc:
        _submit("silo-4", H[:2])
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:  # 아직 대기
        alignment_service.get_intersection("a1", "silo-4")
    assert exc.value.status_code == 409

    _submit("silo-5", [H[5], H[2], H[1], H[4]])
    job = alignment_service.get_alignment("a1")
    assert job.status == "ready"
    assert job.intersection_size == 2
    assert {p.silo_id: p.submitted for p in job.participants} == {"silo-4": 4, "silo-5": 4}

    result = alignment_service.get_intersection("a1", "silo-5")
    assert result.hashed_keys == sorted([H[1], H[2]])
    with pytest.raises(HTTPException) as exc:
        alignment_service.get_intersection("a1", "silo-9")
    assert exc.value.status_code == 403


@pytest.mark.unit
def test_reports_decide_order_consistency():
    _create()
    _submit("silo-4", H[:3])
    _submit("silo-5", H[1:4])
    digest = "d" * 64

    alignment_service.report_alignment(
        "a1", AlignmentReport(silo_id="silo-4", matched=2, excluded=1, order_digest=digest))
    assert alignment_service.get_alignment("a1").order_consistent is None

    job = alignment_service.report_alignment(
        "a1", AlignmentReport(silo_id="silo-5", matched=2, excluded=1, order_digest=digest))
    assert job.order_consistent is True
    assert [(p.matched, p.excluded) for p in job.participants] == [(2, 1), (2, 1)]


@pytest.mark.unit
def test_report_with_different_order_is_inconsistent():
    _create()
    _submit("silo-4", H[:3])
    _submit("silo-5", H[1:4])
    alignment_service.report_alignment(
        "a1", AlignmentReport(silo_id="silo-4", matched=2, excluded=1, order_digest="d" * 64))
    job = alignment_service.report_alignment(
        "a1", AlignmentReport(silo_id="silo-5", matched=2, excluded=1, order_digest="e" * 64))

    assert job.order_consistent is False


def _clean_ids(silo_id: str, tmp_path) -> list[dict]:
    mapping = {**synthetic.HVC_MAPPING, "common_schema": {
        k: v for k, v in synthetic.HVC_MAPPING["common_schema"].items() if k != "x2"}}
    steps = [
        {"type": "map_schema", "params": {"sources": ["period_a", "period_b", "entity"]}},
        {"type": "union_sources", "params": {"sources": ["period_a", "period_b"],
                                             "into": "periods"}},
        {"type": "join_sources", "params": {"left": "periods", "right": "entity",
                                            "into": "base"}},
        {"type": "validate_schema", "params": {}},
    ]
    from silo_sdk.integration import load_sources

    tables = load_sources(synthetic.write_sources(silo_id, tmp_path / silo_id))
    rows, _ = apply_recipe(tables, steps, mapping=mapping)
    return rows


@pytest.mark.unit
def test_two_silos_align_without_sending_raw_ids(tmp_path):
    """silo-4·5 실제 합성 원천 — 교집합·제외 수, 정렬 순서 일치, 서버 기록에 원본 id 없음."""
    from config import cleaning_manager

    rows = {s: _clean_ids(s, tmp_path) for s in ("silo-4", "silo-5")}
    _create()
    digests = {s: hash_ids([r["id"] for r in rows[s]], KEY) for s in rows}
    for silo_id, d in digests.items():
        _submit(silo_id, list(d))
    intersection = alignment_service.get_intersection("a1", "silo-4").hashed_keys

    aligned = {}
    for silo_id in rows:
        aligned[silo_id], rep = align_rows(rows[silo_id], "id", intersection, KEY)
        job = alignment_service.report_alignment(
            "a1", AlignmentReport(silo_id=silo_id, **rep))

    true_shared = {r["id"] for r in rows["silo-4"]} & {r["id"] for r in rows["silo-5"]}
    assert len(intersection) == len(true_shared) > 0
    assert [r["id"] for r in aligned["silo-4"]] == [r["id"] for r in aligned["silo-5"]]
    assert job.order_consistent is True
    assert all(p.excluded == p.submitted - p.matched > 0 for p in job.participants)

    stored = cleaning_manager.ALIGNMENTS_FILE.read_text(encoding="utf-8")
    all_ids = {r["id"] for silo_rows in rows.values() for r in silo_rows}
    assert not [i for i in all_ids if i in stored], "서버 기록에 원본 id가 있으면 안 된다"


@pytest.mark.unit
def test_alignment_api_flow():
    from main import app

    client = TestClient(app)
    r = client.post("/api/alignment-jobs", json={"alignment_id": "a1",
                                                 "silo_ids": ["silo-4", "silo-5"]})
    assert r.status_code == 201
    assert client.post("/api/alignment-jobs/a1/submit",
                       json={"silo_id": "silo-4", "hashed_keys": ["E1"]}).status_code == 422
    for silo_id, hashes in (("silo-4", H[:3]), ("silo-5", H[2:5])):
        r = client.post("/api/alignment-jobs/a1/submit",
                        json={"silo_id": silo_id, "hashed_keys": hashes})
        assert r.status_code == 202
    r = client.get("/api/alignment-jobs/a1/intersection", params={"silo_id": "silo-5"})
    assert r.json()["hashed_keys"] == [H[2]]
    assert client.get("/api/alignment-jobs/a1").json()["intersection_size"] == 1
    assert [j["alignment_id"] for j in client.get("/api/alignment-jobs").json()] == ["a1"]


@pytest.mark.unit
def test_server_code_never_reads_the_silo_align_key():
    """공유 키는 사일로 환경변수에만 — 서버 코드(api·services·models·config·storage)는 읽지 않는다."""
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    server_files = [p for d in ("api", "services", "models", "config", "storage")
                    for p in (backend / d).rglob("*.py")]
    server_files += [backend / "main.py", backend / "cleaning_main.py"]
    assert server_files
    assert not [p.name for p in server_files if "FED_ALIGN_KEY" in p.read_text(encoding="utf-8")]
