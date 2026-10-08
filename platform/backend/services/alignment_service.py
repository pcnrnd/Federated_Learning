"""사일로 간 수직 정렬 작업 — HMAC 다이제스트 교집합 (원본 id를 받지 않는다).

흐름:
  1. create_alignment — 참여 사일로 지정
  2. submit_hashes   — 사일로마다 1회, HMAC-SHA256 다이제스트 목록 (원본 id 아님)
  3. 모두 제출하면 교집합을 정렬해 저장하고 status=ready
  4. get_intersection — 참여 사일로에게만 교집합 다이제스트를 돌려준다
  5. report_alignment — 사일로가 남긴 수·제외 수·순서 지문을 보고 → order_consistent 판정
"""
from __future__ import annotations

import hashlib
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from config.cleaning_manager import load_alignments, save_alignments
from models.alignment_schemas import (
    AlignmentIntersection,
    AlignmentJob,
    AlignmentJobCreate,
    AlignmentParticipant,
    AlignmentReport,
    AlignmentSubmit,
)

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_entry(alignment_id: str) -> dict[str, Any]:
    raw = load_alignments()
    if alignment_id not in raw:
        raise HTTPException(status_code=404, detail=f"정렬 작업 '{alignment_id}' 없음")
    return raw[alignment_id]


def _save_entry(alignment_id: str, entry: dict[str, Any]) -> None:
    raw = load_alignments()
    raw[alignment_id] = entry
    save_alignments(raw)


def _participant(job: AlignmentJob, silo_id: str) -> int:
    for i, p in enumerate(job.participants):
        if p.silo_id == silo_id:
            return i
    raise HTTPException(
        status_code=403, detail=f"사일로 '{silo_id}'는 정렬 작업 '{job.alignment_id}'의 참여자가 아님"
    )


def list_alignments() -> list[AlignmentJob]:
    jobs = [AlignmentJob(**entry["job"]) for entry in load_alignments().values()]
    jobs.sort(key=lambda j: j.created_at, reverse=True)
    return jobs


def get_alignment(alignment_id: str) -> AlignmentJob:
    return AlignmentJob(**_load_entry(alignment_id)["job"])


def create_alignment(request: AlignmentJobCreate) -> AlignmentJob:
    now = _now_iso()
    job = AlignmentJob(
        alignment_id=request.alignment_id,
        silo_ids=list(request.silo_ids),
        status="waiting",
        participants=[AlignmentParticipant(silo_id=s) for s in request.silo_ids],
        created_at=now,
        updated_at=now,
        notes=request.notes,
    )
    with _lock:
        if request.alignment_id in load_alignments():
            raise HTTPException(status_code=409, detail=f"정렬 작업 '{request.alignment_id}' 중복")
        _save_entry(request.alignment_id, {"job": job.model_dump(), "hashes": {}, "intersection": None})
    logger.info("정렬 작업 생성: %s (silos=%s)", request.alignment_id, request.silo_ids)
    return job


def submit_hashes(alignment_id: str, submit: AlignmentSubmit) -> AlignmentJob:
    """사일로의 다이제스트 목록 등록 — 모두 모이면 교집합을 정렬해 둔다."""
    with _lock:
        entry = _load_entry(alignment_id)
        job = AlignmentJob(**entry["job"])
        idx = _participant(job, submit.silo_id)
        if submit.silo_id in entry["hashes"]:
            raise HTTPException(status_code=409, detail=f"사일로 '{submit.silo_id}'는 이미 제출함")
        hashes = sorted(set(submit.hashed_keys))
        entry["hashes"][submit.silo_id] = hashes
        participants = list(job.participants)
        participants[idx] = participants[idx].model_copy(
            update={
                "submitted": len(hashes),
                "submitted_digest": _digest_lines(hashes),
                "submitted_at": _now_iso(),
            }
        )
        update: dict[str, Any] = {"participants": participants, "updated_at": _now_iso()}
        if len(entry["hashes"]) == len(job.silo_ids):
            common = set.intersection(*(set(h) for h in entry["hashes"].values()))
            entry["intersection"] = sorted(common)
            update.update(status="ready", intersection_size=len(common))
        updated = job.model_copy(update=update)
        entry["job"] = updated.model_dump()
        _save_entry(alignment_id, entry)
    logger.info("정렬 다이제스트 제출: %s silo=%s n=%d", alignment_id, submit.silo_id, len(hashes))
    return updated


def get_intersection(alignment_id: str, silo_id: str) -> AlignmentIntersection:
    entry = _load_entry(alignment_id)
    job = AlignmentJob(**entry["job"])
    _participant(job, silo_id)
    if job.status != "ready":
        raise HTTPException(status_code=409, detail="아직 모든 사일로가 제출하지 않았습니다")
    return AlignmentIntersection(alignment_id=alignment_id, hashed_keys=list(entry["intersection"]))


def _digest_lines(keys: list[str]) -> str:
    return hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()


def _report_problems(job: AlignmentJob, submitted: int | None, matched: int | None,
                     excluded: int | None, order_digest: str | None,
                     intersection: list[str]) -> list[str]:
    problems = []
    if matched != job.intersection_size:
        problems.append(f"남은 수 {matched} ≠ 교집합 크기 {job.intersection_size}")
    if (matched or 0) + (excluded or 0) != submitted:
        problems.append(f"남은 수+제외 수 {(matched or 0) + (excluded or 0)} ≠ 제출 수 {submitted}")
    if order_digest != _digest_lines(intersection):
        problems.append("순서 지문이 서버 교집합 순서와 다릅니다")
    return problems


def _check_report(job: AlignmentJob, mine: AlignmentParticipant, report: AlignmentReport,
                  intersection: list[str]) -> None:
    """보고가 서버 기록과 맞는지 — 맞지 않으면 422 (잘못된 보고를 성공으로 판정하지 않는다).

    남은 수 = 교집합 크기, 남은 수 + 제외 수 = 제출 수, 순서 지문 = 서버 교집합(정렬) 지문.
    """
    problems = _report_problems(job, mine.submitted, report.matched, report.excluded,
                                report.order_digest, intersection)
    if report.submitted is not None and report.submitted != mine.submitted:
        problems.append(f"보고한 제출 수 {report.submitted} ≠ 서버 제출 수 {mine.submitted}")
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))


def report_alignment(alignment_id: str, report: AlignmentReport) -> AlignmentJob:
    with _lock:
        entry = _load_entry(alignment_id)
        job = AlignmentJob(**entry["job"])
        idx = _participant(job, report.silo_id)
        if job.status != "ready":
            raise HTTPException(status_code=409, detail="교집합이 정해지기 전에는 보고할 수 없습니다")
        _check_report(job, job.participants[idx], report, entry["intersection"])
        participants = list(job.participants)
        participants[idx] = participants[idx].model_copy(
            update={
                "matched": report.matched,
                "excluded": report.excluded,
                "order_digest": report.order_digest,
            }
        )
        # 판정은 저장된 모든 보고를 서버 기록과 다시 대조한다 — 검증 도입 전 저장된 보고가
        # 남아 있을 수 있어 새 보고만 믿지 않는다. 틀린 보고가 하나라도 있으면 False.
        reported = [p for p in participants if p.order_digest is not None]
        invalid = [p for p in reported if _report_problems(
            job, p.submitted, p.matched, p.excluded, p.order_digest, entry["intersection"])]
        consistent: bool | None
        if invalid:
            consistent = False
        elif len(reported) == len(participants):
            consistent = True
        else:
            consistent = None
        updated = job.model_copy(
            update={"participants": participants, "order_consistent": consistent,
                    "updated_at": _now_iso()}
        )
        entry["job"] = updated.model_dump()
        _save_entry(alignment_id, entry)
    return updated
