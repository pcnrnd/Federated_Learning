# Flower 서비스 이미지 — SuperLink·SuperNode 공용 (10-21 examples/flower_multisilo/docker/Dockerfile 기반).
#
# 앱 코드는 넣지 않는다. 백엔드가 `flwr run`으로 보내는 FAB(flower_app + 공유 학습 수식 silo_sdk)가
# 실행마다 SuperLink를 거쳐 SuperNode로 전달되고, Flower가 FAB 폴더를 sys.path에 올려 import한다.
# 그래서 이 이미지는 flwr·numpy만 있으면 된다(협업기관 SuperNode도 같은 조건).
#
# 빌드:  docker build -t fed-flower:1.41.0 platform/flower
FROM python:3.11-slim-bookworm

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLWR_DISABLE_RUNTIME_DEPENDENCY_INSTALLATION=1

RUN python -m pip install "flwr==1.41.0" "numpy>=1.26.0,<3"
