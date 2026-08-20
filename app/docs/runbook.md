# 런타임 통합 Runbook

사일로(DiD) → 연합 플랫폼(fed-platform) 순서로 기동하고, probe·대시보드·API Key를 검증한다.

## 1. 사전 조건

| 항목 | 확인 |
|---|---|
| Docker Desktop / dockerd | `docker version` |
| Git clone | `Federated_Learning` 저장소 |
| 포트 충돌 없음 | 8000(플랫폼), 2371–2373(사일로 Docker API), 7001–7006(MinIO) |

## 2. 기동 순서

### Step 1 — 사일로 + `fed-net` 네트워크

```bash
cd silo
docker compose -f compose.silo.yaml up -d --build
```

- `silo-1` ~ `silo-3` privileged 컨테이너 기동
- 외부 네트워크 `fed-net` 생성 (대시보드·플랫폼이 join)

| Silo | Docker API (host) | MinIO API | MinIO Console |
|------|-------------------|-----------|---------------|
| silo-1 | localhost:2371 | 7001 | 7002 |
| silo-2 | localhost:2372 | 7003 | 7004 |
| silo-3 | localhost:2373 | 7005 | 7006 |

### Step 2 — 연합 플랫폼 (fed-platform)

```bash
# 저장소 루트
docker compose -f compose.fed-platform.yaml up -d --build
```

환경 변수 (선택):

```bash
FED_API_KEY=change-me FED_PLATFORM_PORT=8000 \
  docker compose -f compose.fed-platform.yaml up -d --build
```

- `./config` → 컨테이너 `/srv/config` 마운트 (YAML/SQLite 영속화)
- Docker socket 마운트는 패키징/배포 API 사용 시에만 주석 해제

### Step 3 — (선택) 노드 관리 대시보드

사일로 Docker 호스트 CRUD가 필요할 때만:

```bash
cd node_management_v0,2
docker compose -f compose.dashboard.yaml up -d --build
# UI: http://localhost:8000  ← fed-platform과 포트 충돌 주의
```

fed-platform과 동시 운영 시 `FED_PLATFORM_PORT` 또는 dashboard 포트를 분리한다.

## 3. 헬스체크

```bash
curl -s http://localhost:8000/healthz
curl -s http://localhost:8000/readyz | jq .
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/dashboard
# → 200
```

`readyz` checks: `config_dir_exists`, `config_dir_writable`, `scheduler_running`, `templates_available`.

API Key 활성화 시:

```bash
curl -s -H "X-FED-API-Key: change-me" http://localhost:8000/api/models
```

## 4. 데모 데이터 주입

```bash
cd app
python scripts/seed_demo.py --base-url http://localhost:8000
# API Key 사용 시 환경변수 또는 스크립트에 헤더 추가
```

브라우저: http://localhost:8000/dashboard

## 5. 수동 검증 체크리스트 (Docker 미사용 시)

Docker가 없거나 sandbox CI에서는 아래를 **로컬 uvicorn**으로 대체한다.

```bash
cd app
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests/test_runtime_operations.py tests/test_dashboard_e2e.py -q
uvicorn main:app --host 0.0.0.0 --port 8000
```

| # | 확인 | 명령/URL |
|---|---|---|
| 1 | probe | `GET /healthz`, `GET /readyz` |
| 2 | 대시보드 HTML | `GET /dashboard` |
| 3 | 통합 차트 API | `GET /api/dashboard?model_name=...` |
| 4 | API Key | `FED_API_KEY=secret` 후 401/200 |
| 5 | SQLite 백엔드 | `FED_STORAGE=sqlite uvicorn ...` |

## 6. 종료 순서

```bash
docker compose -f compose.fed-platform.yaml down
cd silo && docker compose -f compose.silo.yaml down
```

## 7. 트러블슈팅

| 증상 | 조치 |
|---|---|
| `readyz` 503 scheduler | uvicorn 재기동; lifespan에서 RoundScheduler start 확인 |
| fed-platform build 실패 | `app/Dockerfile` context가 repo 루트인지 확인 |
| 사일로 unreachable | `fed-net` 존재 여부: `docker network ls \| grep fed-net` |
| 배포 API 실패 | compose에 docker.sock 마운트 주석 해제 |

자세한 운영·백업·알림 임계값은 [operations.md](./operations.md) 참조.
