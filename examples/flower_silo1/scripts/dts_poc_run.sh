#!/usr/bin/env bash
# Bounded two-round Flower PoC on DTS. Run only on DTS Linux shell.
set -euo pipefail

POC_TAG="fed-flower-poc-20261021"
POC_ROOT="${POC_ROOT:-$HOME/${POC_TAG}}"
APP_DIR="${POC_ROOT}/app"
OUT_DIR="${POC_ROOT}/output"
EVID_DIR="${POC_ROOT}/evidence"
COMPOSE_FILE="${APP_DIR}/docker/compose.yaml"
BUILD_BUDGET=360
RUN_BUDGET=180
CLEANUP_BUDGET=45
OVERALL_START=$SECONDS

mkdir -p "$OUT_DIR" "$EVID_DIR"
export POC_OUTPUT_DIR="$OUT_DIR"

log() { echo "[$(date -Iseconds)] $*"; }

log "memory_sample_dts"
free -m | tee "$EVID_DIR/dts_memory_before.txt"

log "capture_parent_state_before"
{
  echo "=== docker ps silo ==="
  docker ps --format '{{.ID}} {{.Names}} {{.Image}}' | grep -E '^|silo-' || true
  echo "=== pinned rows ==="
  docker cp "$APP_DIR/scripts/inspect_silo1_rows.py" silo-1:/tmp/inspect_silo1_rows.py 2>/dev/null || true
  docker exec silo-1 python3 /tmp/inspect_silo1_rows.py 2>/dev/null || echo "inspect_skip"
} | tee "$EVID_DIR/parent_before.txt"

backend_probe() {
  local base="${BACKEND_BASE:-http://127.0.0.1:8001}"
  local rounds models
  rounds=$(curl -sf "${base}/api/training-rounds" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "na")
  models=$(curl -sf "${base}/api/models" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "na")
  echo "backend_rounds=${rounds} backend_models=${models} base=${base}"
}

backend_probe | tee "$EVID_DIR/backend_counts_before.txt" || true

log "docker_build budget=${BUILD_BUDGET}s mem=1g"
cd "$APP_DIR/docker"
export DOCKER_BUILDKIT=1
if ! timeout "${BUILD_BUDGET}s" docker compose -f compose.yaml build --progress=plain; then
  log "BUILD_FAILED"
  exit 2
fi

log "docker_up"
timeout 60s docker compose -f compose.yaml up -d

log "wait_supernode"
sleep 8

log "versions_in_image"
docker compose -f compose.yaml exec -T superlink python3 - <<'PY' | tee "$EVID_DIR/versions.txt"
import flwr, numpy, sys
print("python", sys.version.split()[0])
print("flwr", flwr.__version__)
print("numpy", numpy.__version__)
PY

log "flwr_config_and_run budget=${RUN_BUDGET}s"
timeout "${RUN_BUDGET}s" docker compose -f compose.yaml exec -T superlink sh -ec '
  mkdir -p /output /root/.flwr
  CFG=/root/.flwr/config.toml
  if ! grep -q "\[superlink.poc\]" "$CFG" 2>/dev/null; then
    printf "%s\n" "[superlink.poc]" "address = \"127.0.0.1:8000\"" "insecure = true" >> "$CFG"
  fi
  flwr run /app poc --stream 2>&1 | tee /output/flwr_run.log
'

log "collect_logs"
docker compose -f compose.yaml logs --no-color > "$EVID_DIR/compose_logs.txt" 2>&1 || true
docker cp fed-flower-poc-20261021-superlink:/output/flwr_run.log "$EVID_DIR/flwr_run.log" 2>/dev/null || true

if [[ -f "$OUT_DIR/final_weights.npz" ]]; then
  sha256sum "$OUT_DIR/final_weights.npz" | tee "$EVID_DIR/final_weights.sha256"
else
  log "MISSING final_weights.npz"
  exit 3
fi

log "cleanup budget=${CLEANUP_BUDGET}s"
timeout "${CLEANUP_BUDGET}s" docker compose -f compose.yaml down --remove-orphans || true

log "capture_parent_state_after"
{
  docker ps --format '{{.ID}} {{.Names}} {{.Image}}' | grep -E 'fed-flower-poc|silo-' || true
} | tee "$EVID_DIR/parent_after.txt"

backend_probe | tee "$EVID_DIR/backend_counts_after.txt" || true

free -m | tee "$EVID_DIR/dts_memory_after.txt"
log "overall_elapsed_sec=$((SECONDS - OVERALL_START))"
