#!/bin/bash

# 2. Docker 데몬 시작 (백그라운드)
# - host 설정을 통해 내부 socket과 외부 TCP 포트(2375) 모두 엽니다.
dockerd --host=unix:///var/run/docker.sock --host=tcp://0.0.0.0:2375 &

# 3. Docker가 완전히 켜질 때까지 잠시 대기
echo "Waiting for Docker daemon to start..."
while (! docker stats --no-stream > /dev/null 2>&1); do
  # Docker가 아직 안 켜졌으면 1초 대기
  sleep 1
done
echo "Docker daemon started!"

# 4. MinIO 설치 및 실행 (Silo 3)
SILO_NUM=3
echo "Starting MinIO for silo-${SILO_NUM}..."
MINIO_COMPOSE="/usr/local/bin/compose.minio.yaml"
# MinIO 루트 계정은 저장소에 두지 않는다. MINIO_ROOT_USER·MINIO_ROOT_PASSWORD 를 둘 다 주지 않으면
# 첫 기동 때 임의 값을 만들어 사일로 볼륨에 보관(0600)하고 재기동에도 같은 값을 쓴다.
MINIO_CRED_FILE=/var/lib/docker/.minio-root.env
if [ -z "${MINIO_ROOT_USER:-}" ] || [ -z "${MINIO_ROOT_PASSWORD:-}" ]; then
    [ -s "$MINIO_CRED_FILE" ] || (umask 077; for k in MINIO_ROOT_USER MINIO_ROOT_PASSWORD; do
        printf '%s=%s\n' "$k" "$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    done > "$MINIO_CRED_FILE")
    # shellcheck disable=SC1090
    . "$MINIO_CRED_FILE"
fi
export MINIO_ROOT_USER MINIO_ROOT_PASSWORD

# MinIO compose 파일이 존재하는지 확인
if [ -f "$MINIO_COMPOSE" ]; then
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

# 5. 컨테이너가 꺼지지 않도록 무한 대기 (Tail logs)
tail -f /dev/null

