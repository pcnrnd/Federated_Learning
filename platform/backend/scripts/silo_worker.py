"""사일로 컨테이너 안에서 실행되는 E2E 워커 (표준 라이브러리 + silo_sdk 전용).

정제(clean): 레시피 조회 → 샤드 start → 로컬 데이터에 apply_recipe → 카운터 report.
  레시피에 매핑표(mapping)가 있으면 로컬 원천 파일(--data-dir, 없으면 합성 생성)을,
  없으면 기존 더미 단일 표를 정제한다.
학습(train): 사일로별 non-IID 로컬 데이터 생성 → train_ridge 실학습 → 파라미터 기여 push.
  --recipe-name/--recipe-version 을 주면(train·train-loop·train-edge 공통) 로컬 원천 3유형에
  레시피를 적용한 정제 결과로 학습하고, 정제 전후 행 수·학습 RMSE를 기여와 함께 보낸다.
엣지 집계(train-edge): 자기 실학습 + 하위 파라미터를 combine 해 1건으로 대리 제출 (2단 HFL).
수집(monitor): /proc 실측 리소스(cpu/mem/disk %)를 주기 push — SPA 사일로 리소스 화면 데이터원.
연속학습(train-loop): open 라운드를 폴링해 릿지 실학습 기여 + 로컬 R² 지표를 라운드마다 push.
수직 정렬(align): 정제 결과의 엔터티 id를 공유 키 FED_ALIGN_KEY(사일로 환경변수)로
  HMAC-SHA256 해 다이제스트만 보내고, 서버 교집합만 같은 순서로 로컬 파일에 남긴다.

원시 데이터는 컨테이너 밖으로 나가지 않는다 — 통계·파라미터·백분율만 push된다.

사용 예 (silo-N 컨테이너 내부, PYTHONPATH=/opt):
    python3 silo_worker.py clean --central http://fed-backend:8000 --silo-id silo-1 \
        --job-id job-x --shard-index 0 --recipe-name r --recipe-version 1.0.0
    python3 silo_worker.py train --central http://fed-backend:8000 --silo-id silo-1 \
        --round-id <round_id>
    python3 silo_worker.py train-edge --central http://fed-backend:8000 --silo-id silo-2 \
        --round-id <round_id> --children-json children.json   # '-' = stdin
    python3 silo_worker.py monitor --central http://fed-backend:8000 --silo-id silo-1 \
        --interval 5 --count 0
    python3 silo_worker.py train-loop --central http://fed-backend:8000 --silo-id silo-1 \
        --model e2e-ridge --max-rounds 250
    FED_ALIGN_KEY=... python3 silo_worker.py align --central http://fed-backend:8000 \
        --silo-id silo-4 --alignment-id a1 --recipe-name silo-hvc --recipe-version 1.0.0
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import random
import sys
import time

from silo_sdk import SiloClient, apply_recipe, synthetic, train_ridge
from silo_sdk.resources import sample_resources
from silo_sdk.alignment import align_rows, hash_ids, load_align_key, order_digest
from silo_sdk.client import SiloClientError
from silo_sdk.edge import combine
from silo_sdk.integration import load_sources, schema_fingerprint, CleaningError

FEATURES = ["x1", "x2", "x3"]
# 사일로 로컬 원천 파일 위치 (컨테이너 안 — 사일로 밖으로 나가지 않는다)
DEFAULT_DATA_DIR = os.environ.get("FED_SILO_DATA_DIR", "/srv/silo-data")

# 학습 데이터의 참 모델 — 전 사일로 공통 (E2E에서 집계 결과와 대조)
TRUE_WEIGHTS = [2.0, -3.0, 0.5]
TRUE_BIAS = 4.0


def _seed_of(silo_id: str) -> int:
    digits = "".join(ch for ch in silo_id if ch.isdigit())
    return int(digits) if digits else 7


def _dirty_rows(silo_id: str, n: int = 200) -> list[dict]:
    """정제 대상 더미 데이터 — null/공백/중복/이상치를 의도적으로 섞는다."""
    rng = random.Random(_seed_of(silo_id))
    rows: list[dict] = []
    for i in range(n):
        rows.append(
            {
                "id": i,
                "name": f"  환자-{i} " if rng.random() < 0.3 else f"환자-{i}",
                "age": (
                    None
                    if rng.random() < 0.1
                    else rng.randint(150, 200)
                    if rng.random() < 0.05
                    else rng.randint(1, 99)
                ),
            }
        )
    # 중복 주입 (id 기준 dedupe 대상)
    rows.extend(dict(rows[i]) for i in range(0, n, 20))
    rng.shuffle(rows)
    return rows


def _local_train_rows(silo_id: str) -> list[dict]:
    """사일로별 non-IID 로컬 학습 데이터 — 표본수·특징 분포가 사일로마다 다르다."""
    seed = _seed_of(silo_id)
    rng = random.Random(seed)
    n = 200 + seed * 100  # silo-1=300, silo-2=400, silo-3=500
    shift = (seed - 2) * 1.5  # 특징 분포 이동 (non-IID)
    rows: list[dict] = []
    for _ in range(n):
        x1 = rng.gauss(shift, 1.0)
        x2 = rng.gauss(-shift, 2.0)
        x3 = rng.uniform(0.0, 10.0)
        noise = rng.gauss(0.0, 0.1)
        y = TRUE_WEIGHTS[0] * x1 + TRUE_WEIGHTS[1] * x2 + TRUE_WEIGHTS[2] * x3
        rows.append({"x1": x1, "x2": x2, "x3": x3, "y": y + TRUE_BIAS + noise})
    return rows


def load_local_sources(silo_id: str, data_dir: str) -> dict[str, list[dict]]:
    """사일로 로컬 원천 3유형(4파일)을 읽는다 — 파일이 없으면 합성 원천을 먼저 쓴다."""
    return load_sources(synthetic.ensure_sources(silo_id, data_dir))


def clean_local(
    silo_id: str, data_dir: str, recipe: dict
) -> tuple[int, list[dict], dict[str, int]]:
    """레시피를 로컬 데이터에 적용 → (입력 행 수, 정제 행, 카운터). 행은 로컬에서만 쓴다."""
    if recipe.get("mapping"):
        tables = load_local_sources(silo_id, data_dir)
        rows_in = sum(len(rows) for rows in tables.values())
        cleaned, counters = apply_recipe(tables, recipe["steps"], mapping=recipe["mapping"])
        return rows_in, cleaned, counters
    rows = _dirty_rows(silo_id)
    cleaned, counters = apply_recipe(rows, recipe["steps"])
    return len(rows), cleaned, counters


MAX_ERROR_CHARS = 500


def _clean_shard(client: SiloClient, args: argparse.Namespace, job_id: str, shard_index: int,
                 recipe_name: str, recipe_version: str) -> bool:
    """샤드 1건 정제 → 보고. 시작 뒤 정제가 실패하면 error를 담아 보고하고 False.

    실패를 보고하지 않으면 샤드가 running에 고착돼 잡이 끝나지 않는다. 오류 문구는 예외
    형식과 메시지(통계·컬럼명)뿐이다 — 원시 행은 담지 않는다.
    """
    recipe = client.fetch_cleaning_recipe(recipe_name, recipe_version)
    claimed = client.start_cleaning_shard(job_id, shard_index)
    if claimed.get("shards"):
        from silo_sdk.cleaning_output import execute
        shard = claimed["shards"][shard_index]
        try:
            manifest = execute(getattr(args, "data_dir", DEFAULT_DATA_DIR), args.silo_id,
                               claimed, shard, recipe)
            fields = {key: manifest[key] for key in ("rows_in", "rows_out", "step_counters",
                "schema_fingerprint", "output_id", "output_hash", "source_hash", "recipe_hash")}
            client.report_cleaning_shard(job_id, shard_index, **fields, attempt_id=shard["attempt_id"])
            return True
        except Exception as exc:  # noqa: BLE001
            client.report_cleaning_shard(job_id, shard_index, rows_in=0, rows_out=0, step_counters={},
                attempt_id=shard["attempt_id"], retryable=isinstance(exc, (OSError, TimeoutError)),
                error=(str(exc)[:MAX_ERROR_CHARS] if isinstance(exc, CleaningError)
                       else f"로컬 정제 실행 실패: {type(exc).__name__}"))
            return False

    try:
        rows_in, cleaned, counters = clean_local(
            args.silo_id, getattr(args, "data_dir", DEFAULT_DATA_DIR), recipe
        )
    except Exception as exc:  # noqa: BLE001 — 어떤 실패든 서버에 보고해 샤드를 닫는다
        error = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_CHARS]
        client.report_cleaning_shard(job_id, shard_index, rows_in=0, rows_out=0,
                                     step_counters={}, error=error)
        print(json.dumps({"silo_id": args.silo_id, "job_id": job_id,
                          "shard_index": shard_index, "event": "shard_failed",
                          "error": error}, ensure_ascii=False))
        return False
    job = client.report_cleaning_shard(
        job_id,
        shard_index,
        rows_in=rows_in,
        rows_out=len(cleaned),
        step_counters=counters,
        schema_fingerprint=schema_fingerprint(cleaned),
    )
    print(
        json.dumps(
            {
                "silo_id": args.silo_id,
                "job_id": job_id,
                "shard_index": shard_index,
                "rows_in": rows_in,
                "rows_out": len(cleaned),
                "counters": counters,
                "job_status": job["status"],
            },
            ensure_ascii=False,
        )
    )
    return True


def run_clean(args: argparse.Namespace) -> None:
    """작업 번호를 주면 그 샤드를, 모두 생략하면 내게 배정된 대기 샤드를 차례로 처리한다."""
    client = SiloClient(args.central, args.silo_id)
    given = (args.job_id, args.shard_index, args.recipe_name, args.recipe_version)
    if all(v is not None for v in given):
        if not _clean_shard(client, args, *given):
            raise SystemExit("정제 실패 샤드 1건 (오류를 서버에 보고함)")
        return
    if any(v is not None for v in given):
        raise SystemExit(
            "--job-id·--shard-index·--recipe-name·--recipe-version은 함께 지정하거나 "
            "모두 생략해야 합니다 (생략 = 배정된 대기 샤드 처리)"
        )
    shards = client.list_assigned_shards(status="pending")
    if not shards:
        print(json.dumps({"silo_id": args.silo_id, "event": "no_assigned_shards"},
                         ensure_ascii=False))
        return
    failed = [
        shard["job_id"]
        for shard in shards
        if not _clean_shard(client, args, shard["job_id"], int(shard["shard_index"]),
                            shard["recipe_name"], shard["recipe_version"])
    ]
    if failed:
        raise SystemExit(f"정제 실패 샤드 {len(failed)}건 {failed} (오류를 서버에 보고함)")


# ---------- 사일로 간 수직 정렬 ----------


def _wait_intersection(client: SiloClient, alignment_id: str, wait: float,
                       poll_interval: float) -> list[str]:
    """다른 사일로가 모두 제출할 때까지(409) 기다렸다가 교집합 다이제스트를 받는다."""
    deadline = time.monotonic() + wait
    while True:
        try:
            return list(client.get_alignment_intersection(alignment_id)["hashed_keys"])
        except SiloClientError as exc:
            if exc.status != 409:
                raise
            if time.monotonic() > deadline:
                raise SystemExit(
                    "align 대기 한계 초과 — 다른 사일로가 제출한 뒤 같은 명령으로 다시 실행하면 "
                    "이어서 진행합니다"
                ) from exc
        time.sleep(poll_interval)


def _submit_or_resume(client: SiloClient, alignment_id: str, silo_id: str,
                      digests: list[str]) -> None:
    """다이제스트 제출. 이미 제출했으면(409) 같은 집합인지 확인하고 이어서 진행한다.

    대기 한계 초과·응답 유실 뒤 재실행이 중복 제출 409에서 멈추지 않게 한다. 서버에 남은
    제출 집합 지문과 지금 집합의 지문이 같을 때만 이어 간다 — 그 사이 원천·키·레시피가 바뀌어
    다른 집합이 되면(건수가 같아도) 교집합 기준과 정렬 대상이 어긋나므로 중단한다.
    """
    current = order_digest(sorted(set(digests)))
    try:
        client.submit_alignment_keys(alignment_id, digests)
        return
    except SiloClientError as exc:
        if exc.status != 409:
            raise
        job = client.get_alignment(alignment_id)
        mine = next((p for p in job.get("participants", []) if p.get("silo_id") == silo_id), {})
        if mine.get("submitted_digest") != current:
            raise SystemExit(
                f"align 중단: 이미 제출한 다이제스트 집합(건수 {mine.get('submitted')})이 "
                f"지금 집합(건수 {len(set(digests))})과 다릅니다 — 원천·키·레시피가 바뀌었으면 "
                "새 정렬 작업으로 다시 하세요"
            ) from exc
    print(json.dumps({"silo_id": silo_id, "event": "already_submitted",
                      "submitted": len(digests)}, ensure_ascii=False))


def run_align(args: argparse.Namespace) -> None:
    """정제 결과 엔터티를 다른 사일로와 HMAC 교집합으로 정렬해 로컬에 남긴다."""
    try:
        key = load_align_key()
    except ValueError as exc:
        raise SystemExit(f"align 중단: {exc}") from exc
    client = SiloClient(args.central, args.silo_id)
    recipe = client.fetch_cleaning_recipe(args.recipe_name, args.recipe_version)
    _, cleaned, _ = clean_local(args.silo_id, args.data_dir, recipe)
    key_column = (recipe.get("mapping") or {}).get("key", "id")

    digests = hash_ids((row[key_column] for row in cleaned), key)
    _submit_or_resume(client, args.alignment_id, args.silo_id, list(digests))  # 다이제스트만
    intersection = _wait_intersection(client, args.alignment_id, args.wait, args.poll_interval)
    aligned, report = align_rows(cleaned, key_column, intersection, key)
    client.report_alignment(args.alignment_id, report["matched"], report["excluded"],
                            report["order_digest"])

    out_path = os.path.join(args.data_dir, f"aligned-{args.alignment_id}.csv")
    with open(out_path, "w", encoding="utf-8", newline="") as f:  # 로컬에만 남긴다
        writer = csv.DictWriter(f, fieldnames=list(aligned[0]) if aligned else [key_column])
        writer.writeheader()
        writer.writerows(aligned)
    print(json.dumps({"silo_id": args.silo_id, "rows_after_cleaning": len(cleaned),
                      "intersection": len(intersection), **report}, ensure_ascii=False))


# ---------- 사일로 자기 cgroup 리소스 실측 ----------


def _is_transient(exc: BaseException) -> bool:
    """재시도 가능 오류인가 — 네트워크 단절·타임아웃·429·5xx.

    그 외 4xx(잘못된 payload 등)와 코딩 오류는 다시 보내도 같은 결과이므로 영구 오류로
    본다 — 즉시 종료해 원인이 로그에 드러나게 한다.
    """
    if isinstance(exc, SiloClientError):
        return exc.status == 429 or exc.status >= 500
    return isinstance(exc, (TimeoutError, OSError))  # urllib URLError ⊂ OSError


def run_monitor(args: argparse.Namespace) -> None:
    """리소스 실측치를 주기 push. --count 0 = 무한 (컨테이너 종료 시까지).

    push 실패 내성: SiloClient 자체 재시도(3회 지수 백오프) 위에 이 루프가
    연속 실패 횟수만 센다 — 백오프를 중복하지 않고 다음 주기에 다시 시도하며,
    성공하면 카운터를 리셋한다. --max-failures 연속 실패 시 종료(bounded retry).
    매회 성공 출력(JSON 한 줄)이 곧 생존 신호다.
    """
    client = SiloClient(args.central, args.silo_id)
    pushed = 0
    failures = 0  # 연속 실패 — 성공 시 0으로
    interval = args.interval
    while True:
        resources = sample_resources()
        cpu, mem, disk = resources["cpu_pct"], resources["mem_pct"], resources["disk_pct"]
        try:
            try:
                config = client.get_silo()
                interval = config["collect_interval_seconds"]
            except SiloClientError as config_error:
                if config_error.status != 404:
                    raise
                interval = args.interval  # 이전 서버 설정과도 동작한다.
            client.push_resource_sample(
                cpu, mem, disk_pct=disk, measurement_scope=resources["measurement_scope"],
                unavailable=resources["unavailable"],
                cpu_cores=resources.get("cpu_cores"),
                mem_used_bytes=resources.get("mem_used_bytes"),
                mem_limit_bytes=resources.get("mem_limit_bytes"),
                capabilities=resources.get("capabilities"),
            )
        except Exception as exc:  # noqa: BLE001 — 분류 후 영구 오류는 그대로 다시 던진다
            if not _is_transient(exc):
                raise
            failures += 1
            print(
                json.dumps(
                    {"silo_id": args.silo_id, "event": "transient_error",
                     "failures": failures, "error": str(exc)[:200]},
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if failures >= args.max_failures:
                raise SystemExit(
                    f"monitor 종료: 연속 {failures}회 push 실패 (--max-failures)"
                ) from exc
        else:
            failures = 0
            pushed += 1
            print(
                json.dumps(
                    {"silo_id": args.silo_id, "cpu_pct": cpu, "mem_pct": mem,
                     "disk_pct": disk, "pushed": pushed},
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if args.count > 0 and pushed >= args.count:
                return
        time.sleep(interval)


# ---------- 학습 ----------


def _local_accuracy(rows: list[dict], parameters: list[float]) -> float:
    """로컬 데이터 결정계수 R² (0~1 클립) — 스칼라 지표만 push, 원시 데이터 미전송."""
    *weights, bias = parameters
    ys = [row["y"] for row in rows]
    mean = sum(ys) / len(ys)
    sse = sum(
        (row["y"] - (sum(w * row[c] for w, c in zip(weights, FEATURES)) + bias)) ** 2
        for row in rows
    )
    sst = sum((y - mean) ** 2 for y in ys) or 1.0
    return max(0.0, min(1.0, 1.0 - sse / sst))


_STAT_KEYS = ("rows_before_cleaning", "rows_after_cleaning", "train_rmse")


def _training_rows(args: argparse.Namespace, client: SiloClient,
                   *, resolve_round: bool = True) -> tuple[list[dict], dict]:
    """학습 입력 행과 정제 통계 — 레시피를 지정하면 로컬 원천 정제 결과, 아니면 기존 합성 행."""
    round_id = getattr(args, "round_id", None)
    if round_id and resolve_round:
        entry = client.get_round(round_id)
        reference = entry.get("cleaning_job_id")
        if reference:
            return _linked_output(args, client, reference, entry.get("cleaning_snapshot"))
    name = getattr(args, "recipe_name", None)
    version = getattr(args, "recipe_version", None)
    if not name and not version:
        return _local_train_rows(args.silo_id), {}  # 기존 동작 그대로
    if not (name and version):
        raise SystemExit("--recipe-name과 --recipe-version은 함께 지정해야 합니다")
    recipe = client.fetch_cleaning_recipe(name, version)
    rows_in, cleaned, _ = clean_local(
        args.silo_id, getattr(args, "data_dir", DEFAULT_DATA_DIR), recipe
    )
    return cleaned, {"rows_before_cleaning": rows_in, "rows_after_cleaning": len(cleaned)}


def _linked_output(args, client, job_id, snapshot=None):
    from silo_sdk.cleaning_output import load_output
    if snapshot is not None:
        if args.silo_id not in snapshot:
            raise ValueError("라운드 정제 출력 스냅샷에 사일로가 없습니다")
        rows, manifest = load_output(getattr(args, "data_dir", DEFAULT_DATA_DIR), snapshot[args.silo_id])
        return rows, {"rows_before_cleaning": manifest["rows_in"], "rows_after_cleaning": len(rows)}
    job = client.get_cleaning_job(job_id)
    if job["status"] != "completed":
        raise ValueError("선행 정제 성공 전 학습 불가")
    shard = next((s for s in job["shards"] if s["silo_id"] == args.silo_id), None)
    if shard is None or shard["status"] != "completed" or not shard.get("output_id"):
        raise ValueError("이 사일로의 보존 정제 출력이 없습니다")
    rows, manifest = load_output(getattr(args, "data_dir", DEFAULT_DATA_DIR), shard)
    return rows, {"rows_before_cleaning": manifest["rows_in"], "rows_after_cleaning": len(rows)}


def _rmse(rows: list[dict], parameters: list[float]) -> float:
    """로컬 학습 오차 RMSE — 스칼라만 보고한다."""
    *weights, bias = parameters
    sse = sum(
        (row["y"] - (sum(w * row[c] for w, c in zip(weights, FEATURES)) + bias)) ** 2
        for row in rows
    )
    return math.sqrt(sse / len(rows)) if rows else 0.0


def _with_rmse(stats: dict, rows: list[dict], parameters: list[float]) -> dict:
    """정제 통계가 있을 때만 학습 RMSE를 붙인다 (레시피 미지정이면 빈 dict 그대로)."""
    return {**stats, "train_rmse": _rmse(rows, parameters)} if stats else {}


def _already_contributed(client: SiloClient, round_id: str, silo_id: str) -> bool:
    """409의 원인 판별 — 라운드를 재조회해 내 기여가 실제로 등록돼 있는지 본다.

    True  = 진짜 중복(이전 push가 타임아웃 뒤 서버에는 반영됨) → 기여로 세고 지표 1회 push
    False = 라운드가 마감(aggregating/completed)된 뒤의 기여 → 기여 미반영이므로
            지표를 push하면 집계에 없는 라운드의 accuracy가 중복 계상된다 → 건너뛴다
    재조회 자체가 실패하면(404·일시 오류) 보수적으로 False — 다음 폴링에서 재평가.
    """
    try:
        entry = client.get_round(round_id)
    except (TimeoutError, OSError, SiloClientError):
        return False
    return silo_id in entry.get("contributors", [])


def run_train_loop(args: argparse.Namespace) -> None:
    """open 라운드를 폴링해 릿지 실학습 기여 + 라운드별 accuracy 지표를 push한다.

    min_contributions=멤버수 라운드에서는 전 사일로가 매 라운드 기여해야 집계되므로,
    --max-rounds 회 기여를 마치면 정상 종료한다. --max-idle 초 동안 새 라운드가
    없으면 잔여 라운드 없이 종료된 것으로 보고 현황을 남기고 빠져나온다.
    """
    client = SiloClient(args.central, args.silo_id)
    fallback: tuple[list[dict], dict] | None = None
    linked: dict[tuple[str, str | None], tuple[list[dict], dict]] = {}

    def inputs_for(entry: dict) -> tuple[list[dict], dict]:
        """연결 출력은 즉시 로드. 비연결 라운드의 입력만 필요할 때 준비한다."""
        nonlocal fallback
        job_ref = entry.get("cleaning_job_id")
        if not job_ref:
            if fallback is None:
                fallback = _training_rows(args, client, resolve_round=False)
            return fallback
        snapshot = entry.get("cleaning_snapshot")
        identity = (job_ref, snapshot.get(args.silo_id, {}).get("output_id") if snapshot is not None else None)
        if identity not in linked:
            linked[identity] = _linked_output(args, client, job_ref, snapshot)
        return linked[identity]

    contributed_rounds: set[str] = set()
    idle_deadline = time.monotonic() + args.max_idle
    while len(contributed_rounds) < args.max_rounds:
        if time.monotonic() > idle_deadline:
            print(
                json.dumps(
                    {"silo_id": args.silo_id, "event": "idle_timeout",
                     "contributed": len(contributed_rounds)},
                    ensure_ascii=False,
                ),
                flush=True,
            )
            return
        acted = False
        try:
            open_rounds = client.list_rounds(status="open", model_name=args.model)
        except (TimeoutError, OSError) as exc:
            # 서버 일시 지연/단절 — 워커는 죽지 않고 재폴링한다 (max-idle이 총 상한)
            # 실측: 이력 누적으로 서버 응답이 밀리는 구간에서 타임아웃 연쇄로 워커 사망
            print(
                json.dumps(
                    {"silo_id": args.silo_id, "event": "transient_error",
                     "error": str(exc)[:200]},
                    ensure_ascii=False,
                ),
                flush=True,
            )
            time.sleep(args.poll_interval)
            continue
        for entry in open_rounds:
            round_id = entry["round_id"]
            if round_id in contributed_rounds or args.silo_id in entry.get("contributors", []):
                continue
            try:
                round_rows, round_stats = inputs_for(entry)
            except Exception as exc:  # noqa: BLE001 — 일시 오류만 재폴링, 나머지는 그대로 던진다
                if not _is_transient(exc):
                    raise  # 연결된 정제 작업이 없음(404) 등 — 설정 오류는 드러낸다
                print(json.dumps({"silo_id": args.silo_id, "event": "transient_error",
                                  "round_id": round_id, "error": str(exc)[:200]},
                                 ensure_ascii=False), flush=True)
                break
            result = train_ridge(round_rows, FEATURES, "y", l2=1e-6)
            try:
                client.push_parameters(round_id, result.sample_count, result.parameters,
                                       **_with_rmse(round_stats, round_rows, result.parameters))
            except (TimeoutError, OSError) as exc:
                # push 자체가 타임아웃 — 성공했는지 불명이므로 세지 않고 재폴링
                # (중복 push는 서버가 409로 걸러준다)
                print(
                    json.dumps(
                        {"silo_id": args.silo_id, "event": "transient_error",
                         "round_id": round_id, "error": str(exc)[:200]},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                break
            except SiloClientError as exc:
                # 409 = 이미 기여 또는 라운드 마감, 404 = 목록 조회와 push 사이에 라운드 소멸
                # — 모두 분산 폴링의 정상 경합이므로 워커는 죽지 않는다
                if exc.status not in (404, 409):
                    raise
                if exc.status == 404 or not _already_contributed(
                    client, round_id, args.silo_id
                ):
                    # 기여가 반영되지 않은 라운드 — 세지 않고 지표도 push하지 않는다
                    print(
                        json.dumps(
                            {"silo_id": args.silo_id,
                             "event": "round_gone" if exc.status == 404 else "round_closed",
                             "round_id": round_id},
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    continue
            contributed_rounds.add(round_id)
            acted = True
            idle_deadline = time.monotonic() + args.max_idle
            try:
                client.push_metric(
                    entry["model_name"],
                    entry["version"],
                    "accuracy",
                    _local_accuracy(round_rows, result.parameters),
                )
            except (TimeoutError, OSError, SiloClientError):
                pass  # 지표 push는 best-effort — 기여 진행을 막지 않는다
        if not acted:
            time.sleep(args.poll_interval)
    print(
        json.dumps(
            {"silo_id": args.silo_id, "event": "completed",
             "contributed": len(contributed_rounds)},
            ensure_ascii=False,
        ),
        flush=True,
    )


def run_train(args: argparse.Namespace) -> None:
    client = SiloClient(args.central, args.silo_id)
    rows, stats = _training_rows(args, client)
    result = train_ridge(rows, FEATURES, "y", l2=1e-6)
    stats = _with_rmse(stats, rows, result.parameters)
    if getattr(args, "emit_only", False):
        # 엣지 집계자에게 넘길 하위 결과 1건 (train-edge --children-json 형식) — push 하지 않는다
        print(json.dumps({"silo_id": args.silo_id, "sample_count": result.sample_count,
                          "parameters": result.parameters, **stats}, ensure_ascii=False))
        return
    if not args.round_id:
        raise SystemExit("--round-id가 필요합니다 (--emit-only가 아닐 때)")
    record = client.push_parameters(
        args.round_id, result.sample_count, result.parameters, **stats
    )
    print(
        json.dumps(
            {
                "silo_id": args.silo_id,
                "sample_count": result.sample_count,
                "local_parameters": [round(p, 6) for p in result.parameters],
                "parameter_dim": record["parameter_dim"],
                **stats,
            },
            ensure_ascii=False,
        )
    )


def _load_children(source: str) -> list[dict]:
    """하위 노드의 학습 결과를 읽어들인다 — `-`면 stdin, 아니면 파일 경로.

    하위 파라미터를 실제로 모으는 전송 수단은 사내망 사정에 따라 다르므로 SDK 범위 밖이다
    (설계 스펙 2026-08-21-hfl-server-design.md §4.3). 이 워커는 이미 모인 결과를 JSON으로
    받는 것까지만 책임진다.
    형식: [{"silo_id": str, "sample_count": int, "parameters": [float, ...]}, ...]
    """
    if source == "-":
        raw = sys.stdin.read()
    else:
        with open(source, encoding="utf-8") as f:
            raw = f.read()
    children = json.loads(raw)
    if not isinstance(children, list) or not children:
        raise SystemExit("--children-json: 하위 결과가 비어 있습니다")
    for child in children:
        missing = {"silo_id", "sample_count", "parameters"} - set(child)
        if missing:
            raise SystemExit(f"--children-json: 필드 누락 {sorted(missing)}")
    return children


def _edge_cleaning_stats(own: dict, own_samples: int, children: list[dict]) -> dict:
    """집계자 자신 + 하위의 정제 통계 합 — 모든 참여자가 통계를 가졌을 때만 (아니면 빈 dict).

    행 수는 합, 학습 RMSE는 표본수 가중 합성 sqrt(Σ nᵢ·rmseᵢ² / Σ nᵢ).
    """
    if not own or not all(all(c.get(k) is not None for k in _STAT_KEYS) for c in children):
        return {}
    parts = [(own_samples, own)] + [(int(c["sample_count"]), c) for c in children]
    total = sum(n for n, _ in parts)
    return {
        "rows_before_cleaning": sum(int(s["rows_before_cleaning"]) for _, s in parts),
        "rows_after_cleaning": sum(int(s["rows_after_cleaning"]) for _, s in parts),
        "train_rmse": math.sqrt(sum(n * float(s["train_rmse"]) ** 2 for n, s in parts) / total),
    }


def run_train_edge(args: argparse.Namespace) -> None:
    """엣지 집계자 모드 — 자기 실학습 + 하위 파라미터를 로컬 가중평균해 1건 대리 제출.

    집계자 사일로는 순수 중계자가 아니라 **자신도 로컬 데이터를 가진 사일로**이므로
    자기 학습 결과를 combine 참여 목록의 첫 원소로 넣는다. 빼면 그 표본이 분자·분모
    양쪽에서 사라져 라운드 total_samples가 평면 등가보다 작아진다 — 2026-09-08·09-21
    2단 HFL 실측 7건이 이 누락으로 3300 대신 2900을 기록했다.

    provenance(`aggregated_from`)는 **하위 id만** 담는다 — 서버가 자기 자신 포함을
    422로 거부하며(`training_round_service._verify_aggregated_from` ③), 이 계약은
    이번 정정 범위 밖이다.
    """
    client = SiloClient(args.central, args.silo_id)
    children = _load_children(args.children_json)

    rows, stats = _training_rows(args, client)
    mine = train_ridge(rows, FEATURES, "y", l2=1e-6)
    edge_stats = _edge_cleaning_stats(
        _with_rmse(stats, rows, mine.parameters), mine.sample_count, children
    )

    participants = [(args.silo_id, mine.sample_count, mine.parameters)]
    participants += [
        (c["silo_id"], int(c["sample_count"]), [float(v) for v in c["parameters"]])
        for c in children
    ]
    edge_total, edge_params = combine(participants)

    child_ids = [c["silo_id"] for c in children]
    record = client.push_parameters(
        args.round_id, edge_total, edge_params, aggregated_from=child_ids, **edge_stats
    )
    print(
        json.dumps(
            {
                "silo_id": args.silo_id,
                "own_sample_count": mine.sample_count,
                "child_sample_counts": {
                    c["silo_id"]: int(c["sample_count"]) for c in children
                },
                "edge_total": edge_total,
                "edge_parameters": [round(p, 6) for p in edge_params],
                "aggregated_from": record.get("aggregated_from", child_ids),
            },
            ensure_ascii=False,
        )
    )


def _add_recipe_args(parser: argparse.ArgumentParser) -> None:
    """정제 → 학습: 지정하면 로컬 원천에 레시피를 적용한 결과로 학습한다 (생략 시 기존 동작)."""
    parser.add_argument("--recipe-name", help="정제 레시피 이름 (--recipe-version과 함께)")
    parser.add_argument("--recipe-version", help="정제 레시피 버전")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help="로컬 원천 파일 디렉터리")


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="사일로 E2E 워커")
    sub = parser.add_subparsers(dest="mode", required=True)

    clean = sub.add_parser("clean", help="정제 샤드 처리")
    clean.add_argument("--central", required=True)
    clean.add_argument("--silo-id", required=True)
    # 넷 다 생략하면 내게 배정된 대기 샤드를 서버에서 찾아 처리한다
    clean.add_argument("--job-id")
    clean.add_argument("--shard-index", type=int)
    clean.add_argument("--recipe-name")
    clean.add_argument("--recipe-version")
    clean.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help="로컬 원천 파일 디렉터리")
    clean.set_defaults(func=run_clean)

    continuous = sub.add_parser("clean-loop", help="실제 예약 정제 지속 pull worker")
    continuous.add_argument("--central", required=True)
    continuous.add_argument("--silo-id", required=True)
    continuous.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    continuous.add_argument("--poll-interval", type=float, default=2)
    continuous.add_argument("--concurrency", type=int, default=2)
    continuous.add_argument("--max-cycles", type=int, default=0)
    def run_clean_loop(args):
        from silo_sdk.cleaning_runtime import run
        asyncio.run(run(SiloClient(args.central, args.silo_id), args.data_dir,
                        args.poll_interval, args.concurrency, args.max_cycles))
    continuous.set_defaults(func=run_clean_loop)

    train = sub.add_parser("train", help="로컬 릿지 학습 + 기여 push")
    train.add_argument("--central", required=True)
    train.add_argument("--silo-id", required=True)
    train.add_argument("--round-id", help="기여 대상 라운드 (--emit-only면 생략)")
    train.add_argument("--emit-only", action="store_true",
                       help="push 없이 하위 결과 JSON 1줄만 출력 (train-edge 입력용)")
    _add_recipe_args(train)
    train.set_defaults(func=run_train)

    edge_mode = sub.add_parser(
        "train-edge", help="엣지 집계자 — 자기 학습 + 하위 combine 후 대리 제출"
    )
    edge_mode.add_argument("--central", required=True)
    edge_mode.add_argument("--silo-id", required=True, help="집계자 자신의 사일로 id")
    edge_mode.add_argument("--round-id", required=True)
    edge_mode.add_argument(
        "--children-json",
        required=True,
        help="하위 학습 결과 JSON 경로 ('-' = stdin): "
        "[{silo_id, sample_count, parameters}, ...]",
    )
    _add_recipe_args(edge_mode)
    edge_mode.set_defaults(func=run_train_edge)

    monitor = sub.add_parser("monitor", help="리소스 실측 주기 push")
    monitor.add_argument("--central", required=True)
    monitor.add_argument("--silo-id", required=True)
    monitor.add_argument("--interval", type=float, default=5.0, help="push 주기(초)")
    monitor.add_argument("--count", type=int, default=0, help="push 횟수 (0=무한)")
    monitor.add_argument(
        "--max-failures", type=int, default=12,
        help="연속 push 실패 허용 횟수 — 초과 시 종료 (기본 12 ≈ 5s 주기에서 1분+ 단절 허용)",
    )
    monitor.set_defaults(func=run_monitor)

    align = sub.add_parser("align", help="사일로 간 수직 정렬 (공유 키 HMAC 교집합)")
    align.add_argument("--central", required=True)
    align.add_argument("--silo-id", required=True)
    align.add_argument("--alignment-id", required=True)
    align.add_argument("--recipe-name", required=True)
    align.add_argument("--recipe-version", required=True)
    align.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help="로컬 원천 파일 디렉터리")
    align.add_argument("--wait", type=float, default=300.0, help="다른 사일로 제출 대기 한계(초)")
    align.add_argument("--poll-interval", type=float, default=2.0, help="교집합 조회 주기(초)")
    align.set_defaults(func=run_align)

    loop = sub.add_parser("train-loop", help="open 라운드 폴링 연속 학습 기여")
    loop.add_argument("--central", required=True)
    loop.add_argument("--silo-id", required=True)
    loop.add_argument("--model", required=True, help="기여 대상 모델명 (open 라운드 필터)")
    loop.add_argument("--max-rounds", type=int, default=250, help="기여할 라운드 수")
    loop.add_argument("--poll-interval", type=float, default=0.5, help="라운드 폴링 주기(초)")
    loop.add_argument("--max-idle", type=float, default=120.0, help="새 라운드 무발견 종료 한계(초)")
    _add_recipe_args(loop)
    loop.set_defaults(func=run_train_loop)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
