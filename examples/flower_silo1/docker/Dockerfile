# Task-owned image (does not retag flwr/superlink or flwr/supernode).
FROM python:3.11-slim-bookworm

WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY pyproject.toml README.md LICENSE ./
COPY flower_silo1 ./flower_silo1
RUN python -m pip install -U pip \
    && python -m pip install "flwr==1.41.0" "numpy>=1.26.0,<3" \
    && python -m pip install --no-deps .

# flower-superlink / flower-supernode / flwr CLIs come from the flwr package.
