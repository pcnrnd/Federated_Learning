#!/usr/bin/env bash
# Bounded six-silo two-round Flower run on DTS. Run only on DTS Linux shell.
set -euo pipefail

POC_TAG="fed-flower-six-silos-20261021"
POC_ROOT="${POC_ROOT:-$HOME/${POC_TAG}}"
APP_EXAMPLES="${POC_ROOT}/app"
RUN_SUFFIX="${RUN_SUFFIX:-$(date -u +%Y%m%dT%H%M%SZ)}"
OUT_DIR="${POC_ROOT}/output/${RUN_SUFFIX}"
EVID_DIR="${POC_ROOT}/evidence/${RUN_SUFFIX}"
COMPOSE_DIR="${APP_EXAMPLES}/flower_multisilo/docker"
IMAGE_TAG="fed-flower-six-silos-20261021-app:1.41.0"
DOCKERFILE="${APP_EXAMPLES}/flower_multisilo/docker/Dockerfile"

OVERALL_BUDGET=660
KILL_AFTER=15
BUILD_BUDGET=360
RUN_BUDGET=180
CLEANUP_BUDGET=45
DTS_MIN_AVAIL_MB=4608
RESERVE_SERVICES_MB=$((7 * 512))
POST_RESERVE_MIN_MB=3072
HEAVY_MIN_AVAIL_MB=3072
BUILD_MEM_REQUEST="1g"

COMPOSE_STARTED=0
CLEANUP_RESULT="not_run"
EVIDENCE_CAPTURED=0
WATCHER_PID=""
MAIN_PID=$$
MAIN_RC=0

if [[ "${POC_INNER:-}" != "1" ]]; then
  export POC_INNER=1
  exec timeout --kill-after="${KILL_AFTER}" "${OVERALL_BUDGET}s" bash "$0" "$@"
fi

mkdir -p "$OUT_DIR" "$EVID_DIR"
export POC_OUTPUT_DIR="$OUT_DIR"

log() { echo "[$(date -Iseconds)] $*" | tee -a "$EVID_DIR/run.log"; }

mem_available_mb() {
  python3 - <<'PY'
import subprocess

text = subprocess.check_output(["free", "-m"], text=True, encoding="utf-8")
for line in text.splitlines():
    if line.startswith(("Mem:", "메모리:")):
        print(line.split()[-1])
        break
else:
    raise SystemExit("free_mem_line_missing")
PY
}

record_memory() {
  local label=$1
  {
    echo "label=${label}"
    free -m
    echo "available_mb=$(mem_available_mb)"
  } >> "$EVID_DIR/memory_trace.log"
}

require_dts_memory() {
  local avail
  avail=$(mem_available_mb)
  record_memory "check_${1}"
  if [[ "$avail" -lt "$DTS_MIN_AVAIL_MB" ]]; then
    log "DTS_MEMORY_DENY avail=${avail}MiB need>=${DTS_MIN_AVAIL_MB}MiB"
    exit 10
  fi
  local after=$((avail - RESERVE_SERVICES_MB))
  if [[ "$after" -lt "$POST_RESERVE_MIN_MB" ]]; then
    log "DTS_RESERVE_DENY avail=${avail}MiB after_7x512=${after}MiB need>=${POST_RESERVE_MIN_MB}MiB"
    exit 11
  fi
  log "DTS_MEMORY_OK avail=${avail}MiB projected_after_reserve=${after}MiB"
}

start_pressure_watcher() {
  : > "$EVID_DIR/memory_pressure.log"
  rm -f "$EVID_DIR/MEMORY_PRESSURE"
  (
    while true; do
      avail=$(mem_available_mb)
      if [[ "$avail" -lt "$HEAVY_MIN_AVAIL_MB" ]]; then
        echo "[$(date -Iseconds)] MEMORY_PRESSURE avail=${avail}MiB threshold=${HEAVY_MIN_AVAIL_MB}MiB" \
          >> "$EVID_DIR/memory_pressure.log"
        date -Iseconds > "$EVID_DIR/MEMORY_PRESSURE"
        kill -TERM "${MAIN_PID}" 2>/dev/null || true
        exit 12
      fi
      sleep 2
    done
  ) &
  WATCHER_PID=$!
}

stop_pressure_watcher() {
  if [[ -n "$WATCHER_PID" ]]; then
    kill "$WATCHER_PID" 2>/dev/null || true
    wait "$WATCHER_PID" 2>/dev/null || true
    WATCHER_PID=""
  fi
}

capture_evidence() {
  if [[ "$EVIDENCE_CAPTURED" == "1" ]]; then
    return 0
  fi
  if [[ ! -d "$COMPOSE_DIR" ]]; then
    return 0
  fi
  (
    cd "$COMPOSE_DIR"
    docker compose -f compose.yaml logs --no-color > "$EVID_DIR/compose_logs.txt" 2>&1 || true
  )
  docker cp fed-flower-six-silos-20261021-superlink:/output/flwr_run.log "$EVID_DIR/flwr_run.log" 2>/dev/null || true
  if [[ -f "$OUT_DIR/final_weights.npz" ]]; then
    sha256sum "$OUT_DIR/final_weights.npz" | tee "$EVID_DIR/final_weights.sha256"
  fi
  EVIDENCE_CAPTURED=1
}

owned_compose_down() {
  local rc=0
  if [[ ! -d "$COMPOSE_DIR" ]]; then
    CLEANUP_RESULT="no_compose_dir"
    return 0
  fi
  cd "$COMPOSE_DIR"
  if timeout "${CLEANUP_BUDGET}s" docker compose -f compose.yaml down --remove-orphans; then
    :
  else
    rc=$?
    CLEANUP_RESULT="down_timeout_or_error_rc=${rc}"
    return "$rc"
  fi
  if docker ps -a --filter "name=${POC_TAG}" --format '{{.Names}}' | grep -q .; then
    CLEANUP_RESULT="containers_remain"
    docker ps -a --filter "name=${POC_TAG}" >> "$EVID_DIR/cleanup_leftover.txt" 2>&1 || true
    return 14
  fi
  if docker network ls --format '{{.Name}}' | grep -q 'fed-flower-six-silos-20261021'; then
    CLEANUP_RESULT="network_remain"
    return 15
  fi
  CLEANUP_RESULT="ok"
  return 0
}

on_exit() {
  local rc=$?
  if [[ "$rc" -ne 0 ]]; then
    MAIN_RC=$rc
  fi
  stop_pressure_watcher || true
  capture_evidence || true
  if [[ -f "$EVID_DIR/MEMORY_PRESSURE" ]]; then
    [[ "$MAIN_RC" -eq 0 ]] && MAIN_RC=12
  fi
  if [[ "$COMPOSE_STARTED" == "1" ]]; then
    if ! owned_compose_down; then
      log "CLEANUP_UNRESOLVED result=${CLEANUP_RESULT}"
      [[ "$MAIN_RC" -eq 0 ]] && MAIN_RC=14
    else
      log "CLEANUP_OK result=${CLEANUP_RESULT}"
    fi
  fi
  record_memory "exit"
  log "FINAL_RC=${MAIN_RC} cleanup=${CLEANUP_RESULT} run_suffix=${RUN_SUFFIX}"
  exit "$MAIN_RC"
}
trap on_exit EXIT

backend_probe() {
  local label=$1
  local out="$EVID_DIR/backend_${label}.txt"
  BACKEND_BASE="${BACKEND_BASE:-http://127.0.0.1:18080}" \
  python3 - <<'PY' | tee "$out"
import json
import os
import subprocess
import sys
from collections import Counter

base = os.environ["BACKEND_BASE"].rstrip("/")

def fetch(path: str) -> list:
    url = f"{base}{path}"
    proc = subprocess.run(
        ["curl", "--connect-timeout", "2", "--max-time", "5", "-sf", url],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"curl failed path={path} rc={proc.returncode} err={proc.stderr.strip()}")
    data = json.loads(proc.stdout)
    if not isinstance(data, list):
        raise TypeError(f"{path} expected JSON list, got {type(data).__name__}")
    return data

rounds = fetch("/api/training-rounds")
models = fetch("/api/models")
r_status = Counter(item.get("status") for item in rounds if isinstance(item, dict))
completed = r_status.get("completed", 0)
print(f"base={base}")
print(f"training_rounds_total={len(rounds)}")
print(f"training_rounds_completed={completed}")
print(f"training_rounds_status={dict(sorted(r_status.items()))}")
print(f"models_total={len(models)}")
PY
}

verify_silo_rows_sha() {
  local silo=$1 rel=$2 expected=$3
  docker exec -i "silo-${silo}" python3 - "${silo}" "$rel" "$expected" <<'PY'
import hashlib
import sys
from pathlib import Path

silo_id, rel, expect = sys.argv[1], sys.argv[2], sys.argv[3]
path = Path("/srv/silo-data") / rel
raw = path.read_bytes()
digest = hashlib.sha256(raw).hexdigest()
print(f"silo={silo_id} rows_sha256={digest} path={path}")
if digest != expect:
    raise SystemExit(f"sha mismatch got {digest} expected {expect}")
PY
}

capture_parent_and_rows() {
  local label=$1
  local out="$EVID_DIR/parent_${label}.txt"
  {
    echo "=== silo_parent_containers (expect 6) ==="
    docker ps --filter "name=^silo-" --format '{{.ID}} {{.Names}} {{.Image}}' | sort
    echo "=== poc_containers ==="
    docker ps -a --filter "name=${POC_TAG}" --format '{{.ID}} {{.Names}} {{.Image}}' || true
    echo "=== pinned_rows_metadata ==="
  } | tee "$out"
  verify_silo_rows_sha 1 \
    "fed-final-path603396-20261021/.cleaned/f27880259e7c004a83f7515ca6ad70a792ee7cba6d4897a28994c1689f69f939/rows.json" \
    "8164fad0f8a29f18c677a99ad7e791b76e3c318dc15569d27bd2ea5432837356" | tee -a "$out"
  verify_silo_rows_sha 2 \
    "fed-final-path603396-20261021/.cleaned/f10190bd8e62495e2ccf985aeb98baa784ca3e0df84129064b8b6aae1f5b6fe6/rows.json" \
    "fedb53a0f061d66dd70f0bcde2c00ac0b37ac324025dc99ded835a558cecd8a3" | tee -a "$out"
  verify_silo_rows_sha 3 \
    "fed-final-path603396-20261021/.cleaned/c707626344d8e030dbabc0a21f742ad290a353a7df3f11de47abed1f64d7a3bb/rows.json" \
    "56fc7fca3c7009312db8103e5eacf3a97cb0c06c611e83f3c942d31c17e31984" | tee -a "$out"
  verify_silo_rows_sha 4 \
    "fed-final-path603396-20261021/.cleaned/64bc01df16adbce3ed36cd6704403e14029989e9d55638a70925540d4d398381/rows.json" \
    "060a9293f0409d96edf460cc0ab75a058b893d66c50fba80c3e0cee7bb96d1c0" | tee -a "$out"
  verify_silo_rows_sha 5 \
    "fed-final-path603396-20261021/.cleaned/e1c971cdecfe4180e7481a19150a55fd0a4e31c0ca12b03c9e8a2868e1a34934/rows.json" \
    "4221522eccca8269541119ad7d399e1273099c545ed205941e283eebc67e56ea" | tee -a "$out"
  verify_silo_rows_sha 6 \
    "fed-final-path603396-20261021/.cleaned/bd78e569eaad6e8bc26e17a9e958a6cb2301e74660fe4cd7233978ba24ffe075/rows.json" \
    "9cefe8c8fb94d0d174cfe63f502c7882c5c702c533d3e7cba60f5849a70999ff" | tee -a "$out"
}

wait_supernodes() {
  local i name ok=0
  for n in 1 2 3 4 5 6; do
    name="fed-flower-six-silos-20261021-supernode${n}"
    for i in $(seq 1 45); do
      if docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null | grep -q true; then
        log "${name}_running after_${i}s"
        ok=$((ok + 1))
        break
      fi
      sleep 1
    done
  done
  if [[ "$ok" -ne 6 ]]; then
    log "SUPERNODE_NOT_ALL_RUNNING count=${ok}"
    exit 5
  fi
  sleep 8
}

OVERALL_START=$SECONDS
log "start POC_ROOT=${POC_ROOT} RUN_SUFFIX=${RUN_SUFFIX}"
if [[ -f "${APP_EXAMPLES}/SOURCE_COMMIT.txt" ]]; then
  log "source_commit=$(cat "${APP_EXAMPLES}/SOURCE_COMMIT.txt")"
fi

record_memory "start"
require_dts_memory "pre_build"
backend_probe "before"
capture_parent_and_rows "before"

log "docker_build requested_mem=${BUILD_MEM_REQUEST} context=${APP_EXAMPLES}"
start_pressure_watcher
set +e
timeout "${BUILD_BUDGET}s" docker build \
  --memory="${BUILD_MEM_REQUEST}" \
  --memory-swap="${BUILD_MEM_REQUEST}" \
  -f "${DOCKERFILE}" \
  -t "${IMAGE_TAG}" \
  "${APP_EXAMPLES}" \
  2>&1 | tee "$EVID_DIR/docker_build.log"
BUILD_RC=${PIPESTATUS[0]}
set -e
stop_pressure_watcher
if [[ "$BUILD_RC" -ne 0 ]]; then
  log "BUILD_FAILED rc=${BUILD_RC}"
  exit 2
fi
docker inspect --format='{{.Id}}' "${IMAGE_TAG}" | tee "$EVID_DIR/image_id.txt"
echo "build_mem_requested=${BUILD_MEM_REQUEST}" >> "$EVID_DIR/docker_build.log"

require_dts_memory "pre_up"
cd "$COMPOSE_DIR"
COMPOSE_STARTED=1
log "docker_compose_up (ownership marked)"
timeout 90s docker compose -f compose.yaml up -d --no-build

wait_supernodes

log "versions_and_flwr_cli"
{
  docker compose -f compose.yaml exec -T superlink python3 - <<'PY'
import flwr, numpy, sys
print("python", sys.version.split()[0])
print("flwr", flwr.__version__)
print("numpy", numpy.__version__)
if flwr.__version__ != "1.41.0":
    raise SystemExit(f"unexpected flwr {flwr.__version__}")
PY
  docker compose -f compose.yaml exec -T superlink flwr --help >/dev/null
  docker compose -f compose.yaml exec -T superlink flwr run --help >/dev/null
} | tee "$EVID_DIR/versions.txt"

start_pressure_watcher
set +e
timeout "${RUN_BUDGET}s" docker compose -f compose.yaml exec -T superlink sh -ec '
  mkdir -p /output /root/.flwr
  CFG=/root/.flwr/config.toml
  if ! grep -Fq "[superlink.poc]" "$CFG" 2>/dev/null; then
    printf "%s\n" "[superlink.poc]" "address = \"127.0.0.1:8000\"" "insecure = true" >> "$CFG"
  fi
  flwr run /app poc --stream 2>&1 | tee /output/flwr_run.log
'
RUN_RC=$?
set -e
stop_pressure_watcher
if [[ "$RUN_RC" -ne 0 ]]; then
  log "RUN_FAILED rc=${RUN_RC}"
  exit 3
fi

capture_evidence
if [[ ! -f "$OUT_DIR/final_weights.npz" ]]; then
  log "MISSING final_weights.npz"
  exit 4
fi

MAIN_RC=0
backend_probe "after"
capture_parent_and_rows "after"
record_memory "success"
log "overall_elapsed_sec=$((SECONDS - OVERALL_START))"
