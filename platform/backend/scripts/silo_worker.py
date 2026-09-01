"""사일로 컨테이너 안에서 실행되는 E2E 워커 (표준 라이브러리 + silo_sdk 전용).

정제(clean): 레시피 조회 → 샤드 start → 로컬 더미 데이터에 apply_recipe → 카운터 report.
학습(train): 사일로별 non-IID 로컬 데이터 생성 → train_ridge 실학습 → 파라미터 기여 push.
수집(monitor): /proc 실측 리소스(cpu/mem/disk %)를 주기 push — SPA 사일로 리소스 화면 데이터원.
연속학습(train-loop): open 라운드를 폴링해 릿지 실학습 기여 + 로컬 R² 지표를 라운드마다 push.

원시 데이터는 컨테이너 밖으로 나가지 않는다 — 통계·파라미터·백분율만 push된다.

사용 예 (silo-N 컨테이너 내부, PYTHONPATH=/opt):
    python3 silo_worker.py clean --central http://fed-backend:8000 --silo-id silo-1 \
        --job-id job-x --shard-index 0 --recipe-name r --recipe-version 1.0.0
    python3 silo_worker.py train --central http://fed-backend:8000 --silo-id silo-1 \
        --round-id <round_id>
    python3 silo_worker.py monitor --central http://fed-backend:8000 --silo-id silo-1 \
        --interval 5 --count 0
    python3 silo_worker.py train-loop --central http://fed-backend:8000 --silo-id silo-1 \
        --model e2e-ridge --max-rounds 250
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

from silo_sdk import SiloClient, apply_recipe, train_ridge
from silo_sdk.client import SiloClientError

FEATURES = ["x1", "x2", "x3"]

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


# ---------- 리소스 실측 (/proc — 리눅스 컨테이너 전용) ----------


def _cpu_pct(sample_interval: float = 0.25) -> float:
    """/proc/stat 2회 스냅샷 차이로 CPU 사용률(%)을 계산한다."""

    def snap() -> tuple[int, int]:
        with open("/proc/stat", encoding="ascii") as f:
            fields = [int(v) for v in f.readline().split()[1:]]
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)  # idle + iowait
        return idle, sum(fields)

    idle_a, total_a = snap()
    time.sleep(sample_interval)
    idle_b, total_b = snap()
    delta_total = total_b - total_a
    if delta_total <= 0:
        return 0.0
    return round(100.0 * (1.0 - (idle_b - idle_a) / delta_total), 1)


def _mem_pct() -> float:
    info: dict[str, int] = {}
    with open("/proc/meminfo", encoding="ascii") as f:
        for line in f:
            key, _, rest = line.partition(":")
            info[key] = int(rest.split()[0])
    total = info.get("MemTotal", 0)
    if total <= 0:
        return 0.0
    return round(100.0 * (1.0 - info.get("MemAvailable", total) / total), 1)


def _disk_pct(path: str = "/") -> float:
    st = os.statvfs(path)
    total = st.f_blocks * st.f_frsize
    if total <= 0:
        return 0.0
    return round(100.0 * (1.0 - st.f_bavail * st.f_frsize / total), 1)


def run_monitor(args: argparse.Namespace) -> None:
    """리소스 실측치를 주기 push. --count 0 = 무한 (컨테이너 종료 시까지)."""
    client = SiloClient(args.central, args.silo_id)
    pushed = 0
    while True:
        cpu, mem, disk = _cpu_pct(), _mem_pct(), _disk_pct()
        client.push_resource_sample(cpu, mem, disk_pct=disk)
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
        time.sleep(args.interval)


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


def run_train_loop(args: argparse.Namespace) -> None:
    """open 라운드를 폴링해 릿지 실학습 기여 + 라운드별 accuracy 지표를 push한다.

    min_contributions=멤버수 라운드에서는 전 사일로가 매 라운드 기여해야 집계되므로,
    --max-rounds 회 기여를 마치면 정상 종료한다. --max-idle 초 동안 새 라운드가
    없으면 잔여 라운드 없이 종료된 것으로 보고 현황을 남기고 빠져나온다.
    """
    client = SiloClient(args.central, args.silo_id)
    rows = _local_train_rows(args.silo_id)
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
        for entry in client.list_rounds(status="open", model_name=args.model):
            round_id = entry["round_id"]
            if round_id in contributed_rounds or args.silo_id in entry.get("contributors", []):
                continue
            result = train_ridge(rows, FEATURES, "y", l2=1e-6)
            try:
                client.push_parameters(round_id, result.sample_count, result.parameters)
            except SiloClientError as exc:
                # 409 = 이미 기여했거나 라운드가 방금 마감됨 — 스케줄러와의 정상 경합
                if exc.status != 409:
                    raise
            contributed_rounds.add(round_id)
            acted = True
            idle_deadline = time.monotonic() + args.max_idle
            client.push_metric(
                entry["model_name"],
                entry["version"],
                "accuracy",
                _local_accuracy(rows, result.parameters),
            )
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
    rows = _local_train_rows(args.silo_id)
    result = train_ridge(rows, FEATURES, "y", l2=1e-6)
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

    monitor = sub.add_parser("monitor", help="리소스 실측 주기 push")
    monitor.add_argument("--central", required=True)
    monitor.add_argument("--silo-id", required=True)
    monitor.add_argument("--interval", type=float, default=5.0, help="push 주기(초)")
    monitor.add_argument("--count", type=int, default=0, help="push 횟수 (0=무한)")
    monitor.set_defaults(func=run_monitor)

    loop = sub.add_parser("train-loop", help="open 라운드 폴링 연속 학습 기여")
    loop.add_argument("--central", required=True)
    loop.add_argument("--silo-id", required=True)
    loop.add_argument("--model", required=True, help="기여 대상 모델명 (open 라운드 필터)")
    loop.add_argument("--max-rounds", type=int, default=250, help="기여할 라운드 수")
    loop.add_argument("--poll-interval", type=float, default=0.5, help="라운드 폴링 주기(초)")
    loop.add_argument("--max-idle", type=float, default=120.0, help="새 라운드 무발견 종료 한계(초)")
    loop.set_defaults(func=run_train_loop)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
