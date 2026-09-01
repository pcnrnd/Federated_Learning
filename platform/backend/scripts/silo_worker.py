"""사일로 컨테이너 안에서 실행되는 E2E 워커 (표준 라이브러리 + silo_sdk 전용).

정제(clean): 레시피 조회 → 샤드 start → 로컬 더미 데이터에 apply_recipe → 카운터 report.
학습(train): 사일로별 non-IID 로컬 데이터 생성 → train_ridge 실학습 → 파라미터 기여 push.

원시 데이터는 컨테이너 밖으로 나가지 않는다 — 통계·파라미터만 push된다.

사용 예 (silo-N 컨테이너 내부, PYTHONPATH=/opt):
    python3 silo_worker.py clean --central http://fed-backend:8000 --silo-id silo-1 \
        --job-id job-x --shard-index 0 --recipe-name r --recipe-version 1.0.0
    python3 silo_worker.py train --central http://fed-backend:8000 --silo-id silo-1 \
        --round-id <round_id>
"""

from __future__ import annotations

import argparse
import json
import random
import sys

from silo_sdk import SiloClient, apply_recipe, train_ridge

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


def run_clean(args: argparse.Namespace) -> None:
    client = SiloClient(args.central, args.silo_id)
    recipe = client.fetch_cleaning_recipe(args.recipe_name, args.recipe_version)
    client.start_cleaning_shard(args.job_id, args.shard_index)

    rows = _dirty_rows(args.silo_id)
    cleaned, counters = apply_recipe(rows, recipe["steps"])
    job = client.report_cleaning_shard(
        args.job_id,
        args.shard_index,
        rows_in=len(rows),
        rows_out=len(cleaned),
        step_counters=counters,
    )
    print(
        json.dumps(
            {
                "silo_id": args.silo_id,
                "rows_in": len(rows),
                "rows_out": len(cleaned),
                "counters": counters,
                "job_status": job["status"],
            },
            ensure_ascii=False,
        )
    )


def run_train(args: argparse.Namespace) -> None:
    client = SiloClient(args.central, args.silo_id)
    rows = _local_train_rows(args.silo_id)
    result = train_ridge(rows, ["x1", "x2", "x3"], "y", l2=1e-6)
    record = client.push_parameters(
        args.round_id, result.sample_count, result.parameters
    )
    print(
        json.dumps(
            {
                "silo_id": args.silo_id,
                "sample_count": result.sample_count,
                "local_parameters": [round(p, 6) for p in result.parameters],
                "parameter_dim": record["parameter_dim"],
            },
            ensure_ascii=False,
        )
    )


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="사일로 E2E 워커")
    sub = parser.add_subparsers(dest="mode", required=True)

    clean = sub.add_parser("clean", help="정제 샤드 처리")
    clean.add_argument("--central", required=True)
    clean.add_argument("--silo-id", required=True)
    clean.add_argument("--job-id", required=True)
    clean.add_argument("--shard-index", type=int, required=True)
    clean.add_argument("--recipe-name", required=True)
    clean.add_argument("--recipe-version", required=True)
    clean.set_defaults(func=run_clean)

    train = sub.add_parser("train", help="로컬 릿지 학습 + 기여 push")
    train.add_argument("--central", required=True)
    train.add_argument("--silo-id", required=True)
    train.add_argument("--round-id", required=True)
    train.set_defaults(func=run_train)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
