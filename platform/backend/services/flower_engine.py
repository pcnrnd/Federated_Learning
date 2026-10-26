"""engine=flower 라운드 실행기 — Flower 실행 제출·상태 확인·취소·결과 반영.

- 라운드 1개 = `flwr run` 1회. SuperLink 전체에서 진행 중인 Flower 실행은 동시에 1개뿐이다.
- 제어는 flwr CLI subprocess(`--format json`), 연결 설정은 백엔드 전용 FLWR_HOME에 만든다.
  flwr 1.41의 JSON 모드는 실패해도 종료 코드 0으로 {"success": false, "error-message"}를 내므로
  종료 코드가 아니라 success로 판정한다 (flwr/cli/utils.py cli_output_handler, supercore/logger.py
  print_json_error).
- 백엔드와 SuperLink(ServerApp)는 교환 폴더를 같은 경로로 마운트한다. 라운드마다
  `<교환 폴더>/<round_id>/`에 request.json·app/(FAB 원본)을 쓰고 ServerApp이 result.json을 쓴다.
- 결과는 training_round_service.complete_external_round로 자체 엔진과 같은 기여·집계·모델 기록이 된다.
"""
from __future__ import annotations

import json
import logging
import math
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from models.federated_schemas import TrainingRound
from services import training_job_service, training_round_service
from silo_sdk import training_protocol as protocol

logger = logging.getLogger(__name__)

ENV_SUPERLINK = "FED_FLOWER_SUPERLINK"  # SuperLink Control API 주소(host:port). 없으면 engine=flower 거절
ENV_EXCHANGE = "FED_FLOWER_EXCHANGE_DIR"  # 백엔드·SuperLink 공용 교환 볼륨 (양쪽 같은 경로)
ENV_TIMEOUT = "FED_FLOWER_RUN_TIMEOUT"  # 제출부터 결과까지 제한 시간(초)
ENV_HOME = "FED_FLOWER_HOME"  # 백엔드 전용 FLWR_HOME
DEFAULT_EXCHANGE = "/srv/flower-exchange"
DEFAULT_TIMEOUT_SECONDS = 600.0
CLI_TIMEOUT_SECONDS = 30.0
CONNECTION = "fed"
# Q4: 같은 float64 연산(silo_sdk)을 쓰므로 차이는 합산 순서(계층 대표 → 전역 vs 평면)뿐이다.
AGGREGATE_RTOL = 1e-9
AGGREGATE_ATOL = 1e-12
REQUEST_FIELDS = ("round_id", "model_name", "version", "member_snapshot", "cluster_snapshot",
                  "cleaning_job_id", "cleaning_snapshot", "learning", "base_parameters",
                  "base_checksum", "space_checksum")
_BACKEND_DIR = Path(__file__).resolve().parent.parent


class FlowerCliError(RuntimeError):
    pass


def superlink_address() -> str:
    return os.getenv(ENV_SUPERLINK, "").strip()


def require_configured() -> None:
    if not superlink_address():
        raise HTTPException(status_code=422, detail=(
            f"SuperLink 주소({ENV_SUPERLINK})가 설정되지 않아 Flower 엔진 작업을 만들 수 없습니다"))


def _exchange_dir() -> Path:
    return Path(os.getenv(ENV_EXCHANGE) or DEFAULT_EXCHANGE)


def _timeout_seconds() -> float:
    try:
        return float(os.getenv(ENV_TIMEOUT) or DEFAULT_TIMEOUT_SECONDS)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _flwr_home() -> Path:
    home = Path(os.getenv(ENV_HOME) or Path(tempfile.gettempdir()) / "fed-flwr-home")
    home.mkdir(parents=True, exist_ok=True)
    # 주소 변경을 바로 반영하도록 매번 다시 쓴다 (파일 하나, 수십 바이트)
    (home / "config.toml").write_text(
        f'[superlink]\ndefault = "{CONNECTION}"\n\n[superlink.{CONNECTION}]\n'
        f"address = {json.dumps(superlink_address())}\ninsecure = true\n", encoding="utf-8")
    return home


def _flwr_bin() -> str:
    # 백엔드와 같은 가상환경의 flwr를 우선 (이미지·로컬 venv 모두 python 옆 bin/Scripts)
    return shutil.which("flwr", path=str(Path(sys.executable).parent)) or shutil.which("flwr") or "flwr"


def _parse_json(stdout: str) -> dict:
    start = stdout.find("{")
    if start < 0:
        return {}
    try:
        payload, _ = json.JSONDecoder().raw_decode(stdout[start:])
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _cli(*args: str) -> dict:
    env = {**os.environ, "FLWR_HOME": str(_flwr_home())}
    try:
        proc = subprocess.run([_flwr_bin(), *args, "--format", "json"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=CLI_TIMEOUT_SECONDS, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FlowerCliError(f"flwr {args[0]} 실행 실패: {type(exc).__name__}") from exc
    payload = _parse_json(proc.stdout)
    if payload.get("success") is not True:
        message = payload.get("error-message") or proc.stderr.strip()[-300:] or f"exit {proc.returncode}"
        raise FlowerCliError(f"flwr {args[0]}: {' '.join(str(message).split())}")
    return payload


def run_status(run_id: int) -> tuple[str, str]:
    """(status, details). status: pending|starting|running|finished:completed|failed|stopped."""
    runs = _cli("ls", CONNECTION, "--run-id", str(run_id)).get("runs") or []
    if not runs:
        raise FlowerCliError(f"flwr ls: run {run_id} 없음")
    return str(runs[0].get("status", "")), str(runs[0].get("status-details", ""))


def _busy() -> bool:
    """SuperLink에 끝나지 않은 실행이 있으면 True (백엔드 밖에서 제출된 실행·재시작 고아 포함)."""
    runs = _cli("ls", CONNECTION).get("runs") or []
    return any(not str(run.get("status", "")).startswith("finished") for run in runs)


def stop_run(run_id: int) -> None:
    _cli("stop", str(run_id), CONNECTION)


def _stage_app(target: Path) -> None:
    """FAB 원본 폴더: pyproject·LICENSE + flower_app/ + silo_sdk/(공유 학습 수식). 백엔드 소스에서 매번 복사."""
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "pyproject.toml", "LICENSE")
    shutil.copytree(_BACKEND_DIR / "flower_app", target / "flower_app", ignore=ignore, dirs_exist_ok=True)
    shutil.copytree(_BACKEND_DIR / "silo_sdk", target / "silo_sdk", ignore=ignore, dirs_exist_ok=True)
    for name in ("pyproject.toml", "LICENSE"):  # fab-format-version 1은 루트 LICENSE 필수
        shutil.copy2(_BACKEND_DIR / "flower_app" / name, target / name)


def build_request(entry: TrainingRound) -> dict:
    return entry.model_dump(mode="json", include=set(REQUEST_FIELDS))


def submit(entry: TrainingRound) -> int:
    round_dir = _exchange_dir() / entry.round_id
    round_dir.mkdir(parents=True, exist_ok=True)
    (round_dir / "result.json").unlink(missing_ok=True)  # 이전 시도의 결과를 이번 결과로 오인하지 않음
    request = round_dir / "request.json"
    temporary = request.with_suffix(".pending")
    temporary.write_bytes(protocol.encoded(build_request(entry)))
    os.replace(temporary, request)
    _stage_app(round_dir / "app")
    payload = _cli("run", str(round_dir / "app"), CONNECTION,
                   "--run-config", f'round-dir="{round_dir.as_posix()}"')
    return int(payload["run-id"])


def _read_result(round_id: str) -> dict | None:
    path = _exchange_dir() / round_id / "result.json"
    try:
        payload = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) and payload.get("round_id") == round_id else None


def _aggregate_matches(leaves: list[dict], aggregate: list) -> bool:
    _, expected = protocol.weighted(sorted(leaves, key=lambda leaf: leaf["silo_id"]))
    return len(expected) == len(aggregate) and all(
        math.isclose(a, b, rel_tol=AGGREGATE_RTOL, abs_tol=AGGREGATE_ATOL) for a, b in zip(expected, aggregate))


def _finish(entry: TrainingRound, status: str, details: str) -> None:
    result = _read_result(entry.round_id)
    if status == "finished:completed" and result and result.get("status") == "completed":
        try:
            if not _aggregate_matches(result["leaves"], result["aggregate"]):
                raise ValueError("Flower 집계 가중치가 원기여 표본 가중 평균과 허용오차 밖에서 다릅니다")
            training_round_service.complete_external_round(entry.round_id, result["leaves"])
            logger.info("Flower 라운드 %s 완료 (run %s)", entry.round_id, entry.flower_run_id)
        except HTTPException as exc:
            training_round_service.fail_external_round(entry.round_id, f"Flower 결과 반영 실패: {exc.detail}")
        except (ValueError, KeyError, TypeError) as exc:
            training_round_service.fail_external_round(entry.round_id, f"Flower 결과 반영 실패: {exc}")
        return
    reason = (result.get("error") or "결과 파일에 원인 없음") if result else f"결과 파일 없음 ({details})"
    training_round_service.fail_external_round(
        entry.round_id, f"Flower 실행 {status} (run {entry.flower_run_id}): {reason}",
        (result or {}).get("errors"))


def _job_status(entry: TrainingRound) -> str | None:
    try:
        return training_job_service.get_job(entry.job_id).status if entry.job_id else None
    except HTTPException:
        return None


def _elapsed(entry: TrainingRound) -> float:
    started = datetime.fromisoformat(entry.flower_submitted_at or entry.created_at)
    return (datetime.now(timezone.utc) - started).total_seconds()


def _stop_and_fail(entry: TrainingRound, reason: str) -> None:
    try:
        stop_run(entry.flower_run_id)
    except FlowerCliError as exc:
        reason = f"{reason}; 중지 요청 실패: {exc}"
    training_round_service.fail_external_round(entry.round_id, reason)


def _poll(entry: TrainingRound) -> bool:
    """진행 중인 실행 1건 점검. 라운드가 끝났으면(완료·실패 기록) True."""
    timeout = _timeout_seconds()
    try:
        status, details = run_status(entry.flower_run_id)
    except FlowerCliError as exc:
        if _elapsed(entry) <= timeout:
            logger.warning("Flower 라운드 %s 상태 확인 실패(재시도): %s", entry.round_id, exc)
            return False
        training_round_service.fail_external_round(
            entry.round_id, f"Flower 제한 시간 {timeout:.0f}s 초과, 상태 확인 실패: {exc}")
        return True
    if status.startswith("finished"):
        _finish(entry, status, details)
        return True
    if _job_status(entry) == "cancelled":
        _stop_and_fail(entry, f"작업 취소로 Flower 실행 중지 (run {entry.flower_run_id})")
        return True
    if _elapsed(entry) > timeout:
        _stop_and_fail(entry, f"Flower 제한 시간 {timeout:.0f}s 초과 (run {entry.flower_run_id}, 상태 {status})")
        return True
    return False


def _submit_next(waiting: list[TrainingRound]) -> str | None:
    for entry in sorted(waiting, key=lambda r: r.created_at):
        job_status = _job_status(entry)
        if job_status in (None, "cancelled", "completed", "failed"):
            training_round_service.fail_external_round(
                entry.round_id, f"작업 상태 {job_status or '없음'}로 Flower 실행을 제출하지 않음")
            continue
        if job_status != "active":
            continue  # 일시정지: 새 실행을 제출하지 않는다. 재개 뒤 이 라운드부터 이어간다.
        if _busy():
            return None
        try:
            run_id = submit(entry)
        except (FlowerCliError, OSError, KeyError, ValueError) as exc:
            training_round_service.fail_external_round(entry.round_id, f"Flower 실행 제출 실패: {exc}")
            return entry.round_id
        training_round_service.record_flower_run(entry.round_id, run_id)
        logger.info("Flower 라운드 %s 제출: run %s", entry.round_id, run_id)
        return entry.round_id
    return None


def tick() -> list[str]:
    """스케줄러 tick: 진행 중 실행 점검 → 비어 있으면 다음 라운드 1개 제출. 처리한 라운드 ID 반환."""
    rounds = [r for r in training_round_service.list_rounds(status="open") if r.engine == "flower"]
    if not rounds:
        return []
    if not superlink_address():
        logger.warning("Flower 라운드 %d개가 열려 있으나 %s가 없어 대기합니다", len(rounds), ENV_SUPERLINK)
        return []
    try:
        touched = [r.round_id for r in rounds if r.flower_run_id is not None and _poll(r)]
        if any(r.flower_run_id is not None and r.round_id not in touched for r in rounds):
            return touched  # 실행 중인 것이 있으면 새로 제출하지 않음(동시에 1개)
        submitted = _submit_next([r for r in rounds if r.flower_run_id is None])
    except FlowerCliError as exc:
        logger.warning("Flower 제어 실패(다음 tick 재시도): %s", exc)
        return []
    return touched + ([submitted] if submitted else [])
