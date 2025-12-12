#!/bin/bash

# 1. SSH 데몬 시작
service ssh start

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

# 4. 컨테이너가 꺼지지 않도록 무한 대기 (Tail logs)
tail -f /dev/null