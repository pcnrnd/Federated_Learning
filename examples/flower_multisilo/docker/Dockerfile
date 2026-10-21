# Six-silo task image (build context: examples/).
FROM python:3.11-slim-bookworm

WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY flower_multisilo/pyproject.toml flower_multisilo/README.md ./
COPY flower_silo1/LICENSE ./LICENSE
COPY flower_silo1/flower_silo1 ./flower_silo1
RUN python -m pip install -U pip \
    && python -m pip install "flwr==1.41.0" "numpy>=1.26.0,<3" \
    && python -m pip install --no-deps .
