#!/bin/bash

# Trusted deployment must explicitly use a private cgroup namespace. These
# runtime guards supplement that admission; they do not prove namespace identity.
_fed_prepare_cgroup_v2() {
  # Only this script's fixed call uses system paths. Arguments allow inert
  # filesystem tests of the exact function, not a runtime Env/CLI override.
  local cg="$1" proc="$2" marker="$3" startup_pid="$4"
  local began=$SECONDS kind current controllers enabled pid count=0 request="" controller
  if [ ! -e "$cg/cgroup.controllers" ]; then
    return 0  # Preserve the existing cgroup-v1 startup path.
  fi
  if [ "$startup_pid" != "1" ] || [ ! -f "$marker" ] || [ -L "$cg" ] \
      || [ "$(stat -f -c %T "$cg")" != "cgroup2fs" ] \
      || [ ! -w "$cg/cgroup.subtree_control" ]; then
    echo "private cgroup startup guard refused before writes" >&2; return 1
  fi
  IFS= read -r current < "$proc/self/cgroup" || return 1
  [ "$current" = "0::/" ] || { echo "cgroup namespace root required" >&2; return 1; }
  IFS= read -r current < "$proc/1/cgroup" || return 1
  [ "$current" = "0::/" ] || return 1
  IFS= read -r kind < "$cg/cgroup.type" || return 1
  IFS= read -r enabled < "$cg/cgroup.subtree_control" || [ -z "$enabled" ] || return 1
  IFS= read -r controllers < "$cg/cgroup.controllers" || return 1
  if [ "$kind" != "domain" ] || [ -n "$enabled" ] || [ -z "$controllers" ] \
      || [ -e "$cg/fed-dind-init" ] || [ -L "$cg/fed-dind-init" ]; then
    echo "non-fresh private cgroup state refused: type=$kind" >&2; return 1
  fi
  while IFS= read -r pid; do
    [ "$pid" = "1" ] || { echo "non-startup root process refused" >&2; return 1; }
    count=$((count + 1))
  done < "$cg/cgroup.procs"
  [ "$count" -eq 1 ] && [ $((SECONDS - began)) -lt 5 ] || return 1
  for controller in $controllers; do
    [[ "$controller" =~ ^[a-z][a-z0-9_]*$ ]] || return 1
    request="$request +$controller"
  done
  # This fresh leaf and the namespace-root delegation are the only writes.
  mkdir "$cg/fed-dind-init" || return 1
  [ $((SECONDS - began)) -lt 5 ] || return 1
  printf '1\n' > "$cg/fed-dind-init/cgroup.procs" || return 1
  while IFS= read -r pid; do
    echo "root process arrived during private startup; refusing delegation" >&2; return 1
  done < "$cg/cgroup.procs"
  [ $((SECONDS - began)) -lt 5 ] || return 1
  printf '%s\n' "$request" > "$cg/cgroup.subtree_control" || return 1
  IFS= read -r kind < "$cg/cgroup.type" || return 1
  IFS= read -r enabled < "$cg/cgroup.subtree_control" || return 1
  IFS= read -r current < "$proc/self/cgroup" || return 1
  [ "$kind" = "domain" ] && [ "$current" = "0::/fed-dind-init" ] || return 1
  for controller in $controllers; do
    case " $enabled " in *" $controller "*) ;; *) return 1 ;; esac
  done
  while IFS= read -r pid; do
    echo "root process remained after private delegation" >&2; return 1
  done < "$cg/cgroup.procs"
  [ $((SECONDS - began)) -lt 5 ] || return 1
  echo "private cgroup startup prepared: domain root empty; PID1 in owned init leaf"
}

trap 'echo "private startup cancelled before services" >&2; exit 143' TERM
trap 'echo "private startup interrupted before services" >&2; exit 130' INT
if ! _fed_prepare_cgroup_v2 /sys/fs/cgroup /proc /.dockerenv "$$"; then
  echo "private cgroup preparation failed; SSH/Docker/workers not started" >&2
  exit 1
fi
trap - TERM INT


# 1. SSH 데몬 시작
service ssh start

# 2. Docker 데몬 시작 (백그라운드)
# - host 설정을 통해 내부 socket과 외부 TCP 포트(2375) 모두 엽니다.
# - 강제 종료(exit 137)된 컨테이너를 docker start 하면 이전 pid 파일이 남아 있고, 새 컨테이너에서
#   같은 PID를 다른 프로세스가 쓰면 dockerd가 "still running"으로 시작을 거부한다.
#   컨테이너 시작 직후엔 dockerd·containerd가 아직 없으므로 무조건 지운다.
rm -f /var/run/docker.pid /var/run/docker/containerd/containerd.pid
dockerd --host=unix:///var/run/docker.sock --host=tcp://0.0.0.0:2375 &
DOCKERD_PID=$!

# 2-1. 정상 종료 — 이 스크립트가 PID 1이라 처리기가 없으면 docker stop의 SIGTERM이 무시되고
#      유예 시간 뒤 SIGKILL(137)로 끝나 안쪽 dockerd·컨테이너가 정리되지 않는다.
#      수집기를 멈추고 → dockerd에 TERM을 보내 끝날 때까지 기다린 뒤(안쪽 컨테이너 정리) → 0으로 종료.
shutdown() {
  if [ -n "${TRAINING_PID:-}" ]; then
    kill "$TRAINING_PID" 2>/dev/null
    wait "$TRAINING_PID"
  fi
  if [ -n "${CLEANING_PID:-}" ]; then
    kill "$CLEANING_PID" 2>/dev/null
    wait "$CLEANING_PID"
  fi
  echo "Stop signal received — stopping monitor and dockerd..."
  if [ -n "${MONITOR_PID:-}" ]; then
    kill "$MONITOR_PID" 2>/dev/null
    wait "$MONITOR_PID"
  fi
  kill "$DOCKERD_PID" 2>/dev/null
  wait "$DOCKERD_PID"
  exit 0
}
trap shutdown TERM INT

# 3. Docker가 완전히 켜질 때까지 대기 — 상한을 넘기면 MinIO 없이 수집기 기동으로 넘어간다
DOCKERD_WAIT_TIMEOUT="${DOCKERD_WAIT_TIMEOUT:-120}"
echo "Waiting for Docker daemon to start..."
dockerd_deadline=$((SECONDS + DOCKERD_WAIT_TIMEOUT))
while (! docker stats --no-stream > /dev/null 2>&1); do
  if [ "$SECONDS" -ge "$dockerd_deadline" ]; then
    echo "Error: dockerd did not respond within ${DOCKERD_WAIT_TIMEOUT}s — check 'docker logs' and /var/run/docker.pid; continuing without Docker" >&2
    break
  fi
  # Docker가 아직 안 켜졌으면 1초 대기
  sleep 1
done
docker info > /dev/null 2>&1 && echo "Docker daemon started!"

# 4. MinIO 설치 및 실행 (Silo 4)
SILO_NUM=4
echo "Starting MinIO for silo-${SILO_NUM}..."
MINIO_COMPOSE="/usr/local/bin/compose.minio.yaml"

# MinIO compose 파일이 존재하는지 확인
if [ "${FED_MINIO_AUTOSTART:-1}" != "0" ] && [ -f "$MINIO_COMPOSE" ]; then
    # Docker Compose v2 사용 (docker compose 명령어)
    # 만약 v2가 없다면 docker-compose 명령어 시도
    if command -v docker &> /dev/null && docker compose version &> /dev/null; then
        docker compose -f "$MINIO_COMPOSE" up -d
    elif command -v docker-compose &> /dev/null; then
        docker-compose -f "$MINIO_COMPOSE" up -d
    else
        echo "Error: docker compose or docker-compose not found"
        exit 1
    fi
    
    # MinIO 컨테이너 시작 확인
    echo "Waiting for MinIO to start..."
    sleep 3
    if docker ps | grep -q "minio-silo${SILO_NUM}"; then
        echo "MinIO started successfully for silo-${SILO_NUM}!"
    else
        echo "Warning: MinIO container may not have started properly."
    fi
else
    echo "Warning: MinIO compose file not found: $MINIO_COMPOSE"
fi

# 5. 리소스 수집기(monitor) 자동 기동 — compose가 FED_CENTRAL·FED_SILO_ID를 주고
#    FED_MONITOR_AUTOSTART=1일 때만. 워커는 /opt/silo_scripts 마운트(docker cp 불필요).
#    중앙이 늦게 뜨거나 수집기가 죽으면 10초 뒤 다시 띄운다(재기동만으로 수집 재개).
#    ponytail: 로그는 재시작마다 덮어쓰는 /tmp/monitor.log 하나 (5초 주기 1줄 ≈ 하루 2MB)
if [ "${FED_MONITOR_AUTOSTART:-0}" = "1" ] && [ -n "$FED_CENTRAL" ] && [ -n "$FED_SILO_ID" ] \
    && [ -f /opt/silo_scripts/silo_worker.py ]; then
    #    수집기·sleep을 백그라운드로 두고 wait해야 TERM을 받자마자 지금 도는 것($!)을 끄고 끝난다.
    (
        trap 'kill $! 2>/dev/null; exit 0' TERM
        while true; do
            python3 /opt/silo_scripts/silo_worker.py monitor \
                --central "$FED_CENTRAL" --silo-id "$FED_SILO_ID" \
                --interval 5 --count 0 > /tmp/monitor.log 2>&1 &
            wait $!
            sleep 10 & wait $!
        done
    ) &
    MONITOR_PID=$!
    echo "monitor autostart: $FED_SILO_ID -> $FED_CENTRAL"
fi

# 저장된 예약·DAG 정제는 각 사일로의 로컬 파일과 결과 스냅샷만 사용한다.
if [ "${FED_CLEANING_AUTOSTART:-0}" = "1" ] && [ -n "$FED_CENTRAL" ] && [ -n "$FED_SILO_ID" ] \
    && [ -f /opt/silo_scripts/silo_worker.py ]; then
    (
        trap 'kill $! 2>/dev/null; wait $! 2>/dev/null; exit 0' TERM
        while true; do
            python3 /opt/silo_scripts/silo_worker.py clean-loop \
                --central "$FED_CENTRAL" --silo-id "$FED_SILO_ID" \
                > /tmp/cleaning.log 2>&1 &
            wait $!
            sleep 10 & wait $!
        done
    ) &
    CLEANING_PID=$!
fi
# live 학습 HTTP 수신/실제 optimizer. 원천/own/inbox/outbox는 같은 silo-local volume에 보존.
if [ "${FED_TRAINING_AUTOSTART:-0}" = "1" ] && [ -n "$FED_CENTRAL" ] && [ -n "$FED_SILO_ID" ] \
    && [ -f /opt/silo_scripts/silo_worker.py ]; then
    (
        trap 'kill $! 2>/dev/null; wait $! 2>/dev/null; exit 0' TERM
        while true; do
            python3 /opt/silo_scripts/silo_worker.py live-loop \
                --central "$FED_CENTRAL" --silo-id "$FED_SILO_ID" \
                --port "${FED_TRAINING_PORT:-8081}" > /tmp/training.log 2>&1 &
            wait $!
            sleep 10 & wait $!
        done
    ) &
    TRAINING_PID=$!
fi
# 6. 컨테이너가 꺼지지 않도록 무한 대기 — 포그라운드 tail이면 trap이 돌지 않으므로 wait로 기다린다
tail -f /dev/null &
wait $!

