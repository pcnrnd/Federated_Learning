#!/usr/bin/env bash
# Bounded two-round Flower PoC on DTS. Run only on DTS Linux shell.
set -euo pipefail

POC_TAG="fed-flower-poc-20261021"
POC_ROOT="${POC_ROOT:-$HOME/${POC_TAG}}"
APP_DIR="${POC_ROOT}/app"
OUT_DIR="${POC_ROOT}/output"
EVID_DIR="${POC_ROOT}/evidence"
COMPOSE_DIR="${APP_DIR}/docker"
COMPOSE_FILE="${COMPOSE_DIR}/compose.yaml"
IMAGE_TAG="fed-flower-poc-20261021-app:1.41.0"

OVERALL_BUDGET=660
KILL_AFTER=15
BUILD_BUDGET=360
RUN_BUDGET=180
CLEANUP_BUDGET=45
DTS_MIN_AVAIL_MB=4608
HEAVY_MIN_AVAIL_MB=3072
BUILD_MEM_REQUEST="1g"
PINNED_ROWS_SHA="8164fad0f8a29f18c677a99ad7e791b76e3c318dc15569d27bd2ea5432837356"

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
  free -m | awk '/^Mem:/ {print $7}'
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
  log "DTS_MEMORY_OK avail=${avail}MiB"
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
  docker cp fed-flower-poc-20261021-superlink:/output/flwr_run.log "$EVID_DIR/flwr_run.log" 2>/dev/null || true
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
  if docker network ls --format '{{.Name}}' | grep -q '^fed-flower-poc-20261021'; then
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
  log "FINAL_RC=${MAIN_RC} cleanup=${CLEANUP_RESULT}"
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

capture_parent_and_rows() {
  local label=$1
  local out="$EVID_DIR/parent_${label}.txt"
  {
    echo "=== silo_parent_containers (expect 7) ==="
    docker ps --filter "name=^silo-" --format '{{.ID}} {{.Names}} {{.Image}}' | sort
    echo "=== poc_containers ==="
    docker ps -a --filter "name=${POC_TAG}" --format '{{.ID}} {{.Names}} {{.Image}}' || true
    echo "=== pinned_rows_metadata ==="
    docker cp "${APP_DIR}/scripts/inspect_silo1_rows.py" silo-1:/tmp/inspect_silo1_rows.py
    docker exec silo-1 python3 /tmp/inspect_silo1_rows.py
  } | tee "$out"
  grep -q "rows_sha256 ${PINNED_ROWS_SHA}" "$out"
}

OVERALL_START=$SECONDS
log "start POC_ROOT=${POC_ROOT}"

record_memory "start"
require_dts_memory "pre_build"
backend_probe "before"
capture_parent_and_rows "before"

log "docker_build requested_mem=${BUILD_MEM_REQUEST} enforced=docker_build_--memory=${BUILD_MEM_REQUEST}"
start_pressure_watcher
set +e
timeout "${BUILD_BUDGET}s" docker build \
  --memory="${BUILD_MEM_REQUEST}" \
  --memory-swap="${BUILD_MEM_REQUEST}" \
  -f "${APP_DIR}/docker/Dockerfile" \
  -t "${IMAGE_TAG}" \
  "${APP_DIR}" \
  2>&1 | tee "$EVID_DIR/docker_build.log"
BUILD_RC=${PIPESTATUS[0]}
set -e
stop_pressure_watcher
if [[ "$BUILD_RC" -ne 0 ]]; then
  log "BUILD_FAILED rc=${BUILD_RC}"
  exit 2
fi
echo "build_mem_requested=${BUILD_MEM_REQUEST}" >> "$EVID_DIR/docker_build.log"
echo "build_mem_enforced=docker_build_--memory=${BUILD_MEM_REQUEST}" >> "$EVID_DIR/docker_build.log"

require_dts_memory "pre_up"
cd "$COMPOSE_DIR"
log "docker_compose_up"
timeout 60s docker compose -f compose.yaml up -d --no-build
COMPOSE_STARTED=1

log "wait_supernode"
sleep 10

log "versions_and_flwr_cli"
{
  docker compose -f compose.yaml exec -T superlink python3 - <<'PY'
import flwr, numpy, sys
print("python", sys.version.split()[0])
print("flwr", flwr.__version__)
print("numpy", numpy.__version__)
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

# Success path: trap still runs cleanup + after probes
MAIN_RC=0
backend_probe "after"
capture_parent_and_rows "after"
record_memory "success"
log "overall_elapsed_sec=$((SECONDS - OVERALL_START))"
