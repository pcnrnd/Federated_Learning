# -*- coding: utf-8 -*-
"""Phase 2 E2E 중앙 드라이버 — 6사일로 연합 + 250라운드 연속 완주 실측 (호스트에서 실행).

절차:
  [1] 6사일로 그룹 보증 + monitor 데몬 기동 (리소스 실측 주기 push)
  [2] /api/resources/usage 에 6사일로 수집 확인 (SPA 사일로 리소스 화면 데이터원)
  [3] 6사일로 단일 연합 라운드 — 릿지 실학습 기여 → FedAvg → completed  (지표: '사일로 6')
  [4] chain 잡(max_rounds=250) + 6사일로 train-loop 데몬 → 250라운드 연속 완주 (지표: '250라운드')

스택 기동 전제 (platform/ 에서, tick 단축 권장):
    FED_SCHEDULER_INTERVAL=1 docker compose -p fed-platform up -d --build

증거 로그: platform/backend/e2e-phase2.log (utf-8, .gitignore *.log 미추적)
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

# Windows 콘솔(cp949)에서 한글·특수문자 출력이 깨지지 않도록 강제
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_LOG = BACKEND_DIR / "e2e-phase2.log"
GROUP = "e2e-root-group-6"
MODEL = "e2e-ridge6"
VERSION = "1.0.0"
STAMP = time.strftime("%Y%m%d%H%M%S")
CENTRAL_IN_NET = "http://fed-backend:8000"  # 컨테이너망 기준 중앙 URL


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 2 E2E 중앙 드라이버")
    parser.add_argument("--base", default="http://localhost:8000", help="중앙 API 베이스 URL")
    parser.add_argument("--distro", default="Ubuntu-24.04", help="WSL 배포판 이름")
    parser.add_argument(
        "--repo-wsl",
        default="/mnt/f/rnd_github/pcnrnd/Federated_Learning",
        help="WSL에서 본 저장소 절대 경로 (docker cp 소스)",
    )
    parser.add_argument(
        "--silos",
        default="silo-1,silo-2,silo-3,silo-4,silo-5,silo-6",
        help="참여 사일로 컨테이너 이름 (콤마 구분)",
    )
    parser.add_argument("--rounds", type=int, default=250, help="연속 완주 라운드 수")
    parser.add_argument("--timeout-min", type=float, default=60.0, help="250라운드 전체 제한(분)")
    parser.add_argument("--stall-sec", type=float, default=180.0, help="라운드 무진행 판정(초)")
    parser.add_argument("--log", default=str(DEFAULT_LOG), help="증거 로그 파일 경로")
    return parser.parse_args(argv)


ARGS = parse_args(sys.argv[1:])
BASE = ARGS.base
WSL = ["wsl", "-d", ARGS.distro]
SILOS = [s.strip() for s in ARGS.silos.split(",") if s.strip()]

log_file = open(ARGS.log, "w", encoding="utf-8")


def log(msg=""):
    line = f"{time.strftime('%H:%M:%S')} {msg}" if msg else msg
    print(line)
    log_file.write(line + "\n")
    log_file.flush()


def api(method, path, body=None, ok=(200, 201, 202)):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            status = resp.status
            raw = resp.read().decode()
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read().decode(errors="replace")
    parsed = json.loads(raw) if raw else None
    if status not in ok:
        log(f"  {method} {path} -> {status}")
        log(f"    !! body: {raw[:400]}")
        raise SystemExit(f"E2E FAIL: {method} {path} -> {status}")
    return status, parsed


def wsl_run(cmd, timeout=180):
    return subprocess.run(WSL + cmd, capture_output=True, text=True,
                          encoding="utf-8", timeout=timeout)


def silo_exec(silo, args, timeout=180):
    r = wsl_run(["docker", "exec", silo, "python3", "/tmp/silo_worker.py"] + args,
                timeout=timeout)
    out = (r.stdout or "").strip()
    if r.stderr:
        log(f"  [{silo}] stderr: {r.stderr.strip()[:400]}")
    if r.returncode != 0:
        raise SystemExit(f"E2E FAIL: {silo} worker exit {r.returncode}")
    log(f"  [{silo}] exit=0 {out}")
    return json.loads(out)


def silo_daemon(silo, worker_args, log_name):
    """컨테이너 내부에서 워커를 백그라운드 기동, 출력은 /tmp/<log_name>에 남긴다."""
    inner = "python3 /tmp/silo_worker.py " + " ".join(worker_args) + f" > /tmp/{log_name} 2>&1"
    r = wsl_run(["docker", "exec", "-d", silo, "sh", "-c", inner], timeout=60)
    if r.returncode != 0:
        raise SystemExit(f"E2E FAIL: {silo} 데몬 기동 실패: {r.stderr}")


def dump_silo_log(silo, log_name, tail=5):
    r = wsl_run(["docker", "exec", silo, "sh", "-c", f"tail -n {tail} /tmp/{log_name}"],
                timeout=60)
    for line in (r.stdout or "").strip().splitlines():
        log(f"    [{silo}:{log_name}] {line}")


def main():
    log(f"===== Phase 2 E2E ({STAMP}) — 6사일로 연합 + {ARGS.rounds}라운드 연속 완주 =====")

    log(f"[0] 준비 — readyz 대기 + silo_worker.py 배포 ({len(SILOS)}사일로)")
    for _ in range(60):
        try:
            api("GET", "/readyz")
            break
        except (SystemExit, OSError):
            time.sleep(3)
    else:
        raise SystemExit("E2E FAIL: /readyz 미응답")
    for silo in SILOS:
        r = wsl_run(["docker", "cp",
                     f"{ARGS.repo_wsl}/platform/backend/scripts/silo_worker.py",
                     f"{silo}:/tmp/silo_worker.py"], timeout=120)
        if r.returncode != 0:
            raise SystemExit(f"docker cp 실패: {silo}: {r.stderr}")
    log(f"  worker 배포 완료: {', '.join(SILOS)}")

    log(f"[1] 사일로 그룹 보증 — {GROUP} (멤버 {len(SILOS)})")
    payload = {"group_id": GROUP, "description": "Phase2 E2E 6사일로 루트 그룹",
               "member_node_ids": SILOS}
    status, _ = api("POST", "/api/silo-groups", payload, ok=(201, 409))
    if status == 409:
        api("PUT", f"/api/silo-groups/{GROUP}", payload)
    log(f"  그룹 준비 완료 (POST -> {status})")

    log("[1b] 리소스 monitor 데몬 기동 (5초 주기 실측 push)")
    for silo in SILOS:
        silo_daemon(silo, ["monitor", "--central", CENTRAL_IN_NET, "--silo-id", silo,
                           "--interval", "5", "--count", "0"], "monitor.log")

    log("[2] 리소스 수집 검증 — /api/resources/usage 에 6사일로")
    deadline = time.monotonic() + 60
    usage = []
    while time.monotonic() < deadline:
        _, usage = api("GET", "/api/resources/usage")
        seen = {u["silo_id"] for u in usage}
        if set(SILOS) <= seen:
            break
        time.sleep(3)
    else:
        raise SystemExit(f"E2E FAIL: usage 수집 사일로 부족: {sorted(seen)}")
    for u in sorted(usage, key=lambda x: x["silo_id"]):
        if u["silo_id"] in SILOS:
            log(f"  {u['silo_id']}: cpu={u['cpu_pct']}% mem={u['mem_pct']}% "
                f"disk={u['disk_pct']}% over_budget={u['over_budget']}")
    log(f"  ==> 리소스 수집 PASS: {len(SILOS)}사일로 실측치 도착 (SPA 사일로 리소스 화면 데이터원)")

    log(f"[3] 모델 등록 {MODEL}@{VERSION}")
    api("POST", "/api/models", {
        "name": MODEL, "version": VERSION, "framework": "pytorch",
        "weights_path": f"/srv/weights/{MODEL}.pt",
        "metadata": {"algorithm": "fedavg", "note": "Phase2 6사일로 E2E"},
    }, ok=(201, 409))

    log(f"[4] 6사일로 단일 연합 라운드 (min_contributions={len(SILOS)})")
    _, rnd = api("POST", "/api/training-rounds", {
        "model_name": MODEL, "version": VERSION,
        "group_id": GROUP, "min_contributions": len(SILOS),
    })
    round_id = rnd["round_id"]
    log(f"  round_id={round_id} snapshot={rnd['member_snapshot']}")
    locals_ = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(SILOS)) as pool:
        futures = {
            silo: pool.submit(silo_exec, silo,
                              ["train", "--central", CENTRAL_IN_NET,
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
    # 스케줄러 자동 집계 대기 (경합 회피 — 명시 aggregate는 409 가능하므로 폴링으로 확인)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        _, rnd = api("GET", f"/api/training-rounds/{round_id}")
        if rnd["status"] == "completed":
            break
        time.sleep(1)
    assert rnd["status"] == "completed", f"라운드 미완료: {rnd['status']}"
    assert sorted(rnd["contributors"]) == sorted(SILOS)
    assert rnd["total_samples"] == total
    assert rnd["aggregated_parameter_dim"] == 4
    log(f"  status=completed contributors={len(rnd['contributors'])}곳 "
        f"total_samples={rnd['total_samples']} dim={rnd['aggregated_parameter_dim']}")
    log(f"  ==> 6사일로 연합 PASS: {len(SILOS)}개 사일로 릿지 실학습 기여 → FedAvg → completed")

    log(f"[5] {ARGS.rounds}라운드 연속 완주 — chain 잡 + train-loop 데몬")
    job_id = f"e2e-chain250-{STAMP}"
    _, job = api("POST", "/api/training-jobs", {
        "job_id": job_id, "model_name": MODEL, "version": VERSION,
        "group_id": GROUP, "schedule_kind": "chain",
        "min_contributions": len(SILOS), "max_rounds": ARGS.rounds,
        "notes": "Phase2 250라운드 연속 실측",
    })
    log(f"  잡 생성: {job_id} (schedule=chain, max_rounds={ARGS.rounds})")
    for silo in SILOS:
        silo_daemon(silo, ["train-loop", "--central", CENTRAL_IN_NET, "--silo-id", silo,
                           "--model", MODEL, "--max-rounds", str(ARGS.rounds),
                           "--poll-interval", "0.5", "--max-idle", "300"],
                    "train-loop.log")
    log(f"  train-loop 데몬 기동: {len(SILOS)}사일로 (poll 0.5s)")

    started = time.monotonic()
    deadline = started + ARGS.timeout_min * 60
    last_completed, last_progress_at = -1, time.monotonic()
    next_report = 25
    while time.monotonic() < deadline:
        _, job = api("GET", f"/api/training-jobs/{job_id}")
        completed = job["rounds_completed"]
        if completed != last_completed:
            last_completed, last_progress_at = completed, time.monotonic()
        if completed >= next_report:
            elapsed = time.monotonic() - started
            log(f"  진행 {completed}/{ARGS.rounds} 라운드 "
                f"(경과 {elapsed:.0f}s, {completed / elapsed * 60:.1f} 라운드/분, "
                f"failed={job['rounds_failed']})")
            next_report = (completed // 25 + 1) * 25
        if job["status"] == "completed":
            break
        if time.monotonic() - last_progress_at > ARGS.stall_sec:
            log(f"  !! {ARGS.stall_sec:.0f}s 무진행 (completed={completed}) — 사일로 로그 덤프")
            for silo in SILOS:
                dump_silo_log(silo, "train-loop.log")
            raise SystemExit("E2E FAIL: 라운드 진행 정체")
        time.sleep(3)
    else:
        raise SystemExit(f"E2E FAIL: {ARGS.timeout_min}분 내 미완주 (completed={last_completed})")

    duration = time.monotonic() - started
    log(f"  잡 최종: status={job['status']} rounds_completed={job['rounds_completed']} "
        f"rounds_failed={job['rounds_failed']}")
    assert job["status"] == "completed"
    assert job["rounds_completed"] == ARGS.rounds
    assert job["rounds_failed"] == 0

    log("[6] 사후 검증 — 라운드 원장·지표 수집량")
    _, rounds = api("GET", f"/api/training-rounds?model_name={MODEL}&status=completed")
    job_rounds = [r for r in rounds if r.get("notes") == f"auto from job={job_id}"]
    log(f"  completed 라운드: 모델 전체 {len(rounds)}건 / 이번 잡 {len(job_rounds)}건")
    assert len(job_rounds) == ARGS.rounds
    sample_counts = {r["total_samples"] for r in job_rounds}
    dims = {r["aggregated_parameter_dim"] for r in job_rounds}
    log(f"  라운드 불변량: total_samples={sorted(sample_counts)} dim={sorted(dims)}")
    assert sample_counts == {total} and dims == {4}
    _, metrics = api("GET", f"/api/monitoring/metrics?model_name={MODEL}&limit=1")
    log(f"  accuracy 지표 수집: {metrics['total']}건 (라운드당 사일로 6 push)")
    for silo in SILOS:
        dump_silo_log(silo, "train-loop.log", tail=1)

    log("")
    log(f"===== Phase 2 E2E 전체 PASS — 사일로 {len(SILOS)}, {ARGS.rounds}라운드 연속 완주, "
        f"소요 {duration / 60:.1f}분 ({ARGS.rounds / duration * 60:.1f} 라운드/분) =====")


if __name__ == "__main__":
    try:
        main()
    finally:
        log_file.close()
