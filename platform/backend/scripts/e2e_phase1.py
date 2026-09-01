# -*- coding: utf-8 -*-
"""Phase 1 E2E 중앙 드라이버 — 정제 잡 + 실학습 FedAvg 라운드 (호스트에서 실행).

중앙 API는 --base(기본 localhost:8000), 사일로 측 실행은 `wsl docker exec silo-N`.
스택 기동 전제: platform/ 에서 `docker compose -p fed-platform up -d --build`.

사용 예 (저장소 루트, Windows Git Bash):
    python platform/backend/scripts/e2e_phase1.py
    python platform/backend/scripts/e2e_phase1.py --silos silo-1,silo-2,silo-3

증거 로그: platform/backend/e2e-phase1.log (utf-8, .gitignore *.log 미추적)
주의: RoundScheduler(기본 15s tick)가 min_contributions 충족 라운드를 자동 집계하므로
      명시적 aggregate는 200/409 둘 다 정상 경로다.
"""
import argparse
import concurrent.futures
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_LOG = BACKEND_DIR / "e2e-phase1.log"
GROUP = "e2e-root-group"
STAMP = time.strftime("%Y%m%d%H%M%S")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 1 E2E 중앙 드라이버")
    parser.add_argument("--base", default="http://localhost:8000", help="중앙 API 베이스 URL")
    parser.add_argument("--distro", default="Ubuntu-24.04", help="WSL 배포판 이름")
    parser.add_argument(
        "--repo-wsl",
        default="/mnt/f/rnd_github/pcnrnd/Federated_Learning",
        help="WSL에서 본 저장소 절대 경로 (docker cp 소스)",
    )
    parser.add_argument(
        "--silos",
        default="silo-1,silo-2,silo-3",
        help="참여 사일로 컨테이너 이름 (콤마 구분)",
    )
    parser.add_argument("--log", default=str(DEFAULT_LOG), help="증거 로그 파일 경로")
    return parser.parse_args(argv)


ARGS = parse_args(sys.argv[1:])
BASE = ARGS.base
WSL = ["wsl", "-d", ARGS.distro]
SILOS = [s.strip() for s in ARGS.silos.split(",") if s.strip()]

log_file = open(ARGS.log, "w", encoding="utf-8")


def log(msg=""):
    print(msg)
    log_file.write(msg + "\n")
    log_file.flush()


def api(method, path, body=None, ok=(200, 201, 202)):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            raw = resp.read().decode()
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read().decode(errors="replace")
    parsed = json.loads(raw) if raw else None
    log(f"  {method} {path} -> {status}")
    if status not in ok:
        log(f"    !! body: {raw[:400]}")
        raise SystemExit(f"E2E FAIL: {method} {path} -> {status}")
    return status, parsed


def silo_exec(silo, args):
    cmd = WSL + ["docker", "exec", silo, "python3", "/tmp/silo_worker.py"] + args
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=180)
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    log(f"  [{silo}] exit={r.returncode} {out}")
    if err:
        log(f"  [{silo}] stderr: {err[:400]}")
    if r.returncode != 0:
        raise SystemExit(f"E2E FAIL: {silo} worker exit {r.returncode}")
    return json.loads(out)


def deploy_workers():
    for silo in SILOS:
        r = subprocess.run(
            WSL + ["docker", "cp",
                   f"{ARGS.repo_wsl}/platform/backend/scripts/silo_worker.py",
                   f"{silo}:/tmp/silo_worker.py"],
            capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise SystemExit(f"docker cp 실패: {silo}: {r.stderr}")
    log(f"  worker 배포 완료: {', '.join(SILOS)}")


def main():
    log(f"===== Phase 1 E2E ({STAMP}) — 정제 잡 + 실학습 FedAvg =====")

    log("\n[0] 준비 — readyz 대기 + silo_worker.py 배포")
    for _ in range(60):
        try:
            api("GET", "/readyz")
            break
        except (SystemExit, OSError):
            time.sleep(3)
    else:
        raise SystemExit("E2E FAIL: /readyz 미응답")
    deploy_workers()

    log("\n[1] 사일로 그룹 보증 — " + GROUP)
    payload = {"group_id": GROUP, "description": "Phase1 E2E 루트 그룹",
               "member_node_ids": SILOS}
    status, _ = api("POST", "/api/silo-groups", payload, ok=(201, 409))
    if status == 409:
        api("PUT", f"/api/silo-groups/{GROUP}", payload)

    # ---------------- 정제 잡 E2E ----------------
    log("\n[2] 정제 레시피 등록 e2e-basic@1.0.0")
    recipe = {
        "name": "e2e-basic", "version": "1.0.0",
        "description": "Phase1 E2E — 결측 제거·공백 정리·중복 제거·이상치 클립",
        "steps": [
            {"type": "drop_nulls", "params": {"columns": ["age"]}},
            {"type": "trim_whitespace", "params": {"columns": ["name"]}},
            {"type": "dedupe", "params": {"keys": ["id"]}},
            {"type": "clip_outliers", "params": {"column": "age", "lower": 0, "upper": 100}},
        ],
    }
    api("POST", "/api/cleaning-recipes", recipe, ok=(201, 409))

    job_id = f"e2e-clean-{STAMP}"
    log(f"\n[3] 정제 잡 생성 {job_id} (그룹 멤버 {len(SILOS)} → 샤드 {len(SILOS)} 자동 배정)")
    _, job = api("POST", "/api/cleaning-jobs", {
        "job_id": job_id, "recipe_name": "e2e-basic", "recipe_version": "1.0.0",
        "group_id": GROUP, "dataset_label": "patients_2026Q3",
    })
    assign = {s["silo_id"]: s["shard_index"] for s in job["shards"]}
    log(f"  샤드 배정: {assign} status={job['status']}")

    log(f"\n[4] 사일로 {len(SILOS)}곳 silo_sdk 로컬 정제 실행 (컨테이너 내부)")
    for silo in SILOS:
        silo_exec(silo, ["clean", "--central", "http://fed-backend:8000",
                         "--silo-id", silo, "--job-id", job_id,
                         "--shard-index", str(assign[silo]),
                         "--recipe-name", "e2e-basic", "--recipe-version", "1.0.0"])

    log("\n[5] 잡 최종 상태 검증")
    _, job = api("GET", f"/api/cleaning-jobs/{job_id}")
    log(f"  status={job['status']} rows {job['total_rows_in']} -> {job['total_rows_out']}")
    log(f"  aggregated_counters={job['aggregated_counters']}")
    assert job["status"] == "completed", f"잡 상태 {job['status']} != completed"
    assert job["total_rows_in"] == 210 * len(SILOS), job["total_rows_in"]  # 사일로당 210행
    assert job["total_rows_out"] < job["total_rows_in"]
    assert set(job["aggregated_counters"]) == {"drop_nulls", "trim_whitespace", "dedupe", "clip_outliers"}
    shard_sum = sum(s["rows_out"] for s in job["shards"])
    assert shard_sum == job["total_rows_out"]
    log(f"  ==> 정제 E2E PASS: 레시피 등록 → 샤드 {len(SILOS)} 로컬 적용 → 카운터 회수 → completed")

    # ---------------- 실학습 FedAvg E2E ----------------
    log("\n[6] 모델 등록 e2e-ridge@1.0.0")
    api("POST", "/api/models", {
        "name": "e2e-ridge", "version": "1.0.0", "framework": "pytorch",
        "weights_path": "/srv/weights/e2e-ridge.pt",
        "metadata": {"algorithm": "fedavg", "note": "Phase1 실학습 E2E"},
    }, ok=(201, 409))

    log(f"\n[7] 라운드 open (min_contributions={len(SILOS)})")
    _, rnd = api("POST", "/api/training-rounds", {
        "model_name": "e2e-ridge", "version": "1.0.0",
        "group_id": GROUP, "min_contributions": len(SILOS),
    })
    round_id = rnd["round_id"]
    log(f"  round_id={round_id} status={rnd['status']} snapshot={rnd['member_snapshot']}")

    log(f"\n[8] 사일로 {len(SILOS)}곳 순수 파이썬 릿지 실학습 → 기여 push (컨테이너 내부, 병렬)")
    locals_ = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(SILOS)) as pool:
        futures = {
            silo: pool.submit(silo_exec, silo,
                              ["train", "--central", "http://fed-backend:8000",
                               "--silo-id", silo, "--round-id", round_id])
            for silo in SILOS
        }
        for silo, fut in futures.items():
            locals_[silo] = fut.result()

    total = sum(v["sample_count"] for v in locals_.values())
    expected = [
        sum(v["sample_count"] * v["local_parameters"][i] for v in locals_.values()) / total
        for i in range(4)
    ]
    log(f"  기대 가중평균={[round(p, 6) for p in expected]} (참값 [2.0, -3.0, 0.5, 4.0])")

    log("\n[9] 글로벌 FedAvg 집계 (스케줄러 tick과 경합 — 409면 자동 집계가 선점)")
    status, agg = api("POST", f"/api/training-rounds/{round_id}/aggregate", ok=(200, 409))
    if status == 200:
        params = agg["parameters"]
        log(f"  contributor_count={agg['contributor_count']} total_samples={agg['total_samples']}")
        log(f"  aggregated={[round(p, 6) for p in params]}")
        assert agg["contributor_count"] == len(SILOS)
        assert agg["total_samples"] == total
        for got, exp in zip(params, expected):
            assert abs(got - exp) < 1e-6, (got, exp)
        for got, true in zip(params, [2.0, -3.0, 0.5, 4.0]):
            assert abs(got - true) < 0.05, (got, true)
        log("  집계 벡터 = 사일로 로컬 파라미터의 표본수 가중평균 일치 (1e-6)")
    else:
        log("  RoundScheduler가 min_contributions 충족을 감지해 자동 집계함 (정상 동작)")

    log("\n[10] 라운드 최종 상태 검증")
    _, rnd = api("GET", f"/api/training-rounds/{round_id}")
    log(
        f"  status={rnd['status']} contributors={rnd['contributors']} "
        f"total_samples={rnd['total_samples']} dim={rnd['aggregated_parameter_dim']}"
    )
    assert rnd["status"] == "completed"
    assert sorted(rnd["contributors"]) == sorted(SILOS)
    assert rnd["total_samples"] == total
    assert rnd["aggregated_parameter_dim"] == 4
    log(f"  ==> 학습 E2E PASS: 라운드 open → {len(SILOS)}사일로 릿지 실학습 기여 → FedAvg → completed")

    log("\n===== Phase 1 E2E 전체 PASS =====")


if __name__ == "__main__":
    try:
        main()
    finally:
        log_file.close()
