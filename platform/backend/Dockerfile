# 연합컴퓨팅 백엔드 (FastAPI)
#
# 빌드 컨텍스트는 이 파일이 있는 platform/backend/ 다.
# (구 app/Dockerfile은 컨텍스트를 저장소 루트로 전제해 `COPY app/`를 썼으나,
#  app/ 디렉터리가 사라져 빌드가 깨졌다 — 컨텍스트를 백엔드 자신으로 좁혀 해결.)
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    FED_CONFIG_DIR=/srv/config

WORKDIR /srv/app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY . /srv/app/

EXPOSE 8000

# main.py가 `from api import ...` 형제 임포트를 쓰므로 반드시 /srv/app 에서 실행한다
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
