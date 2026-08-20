# 연합컴퓨팅 플랫폼 (Federated Computing Platform)

> R&D 3차년도 — 9개 핵심 작업의 통합 구현체.
> 모든 코드는 `Federated_Learning/app/` 경로에 자기완결적으로 위치한다.

> 현재 루트 `app/`가 연합컴퓨팅 플랫폼의 공식 작업 경로다. 기존
> `node_management_v0,2/`는 Docker 노드/컨테이너 관리 대시보드로 분리된
> 이전 계열이며, 본 문서는 루트 `app/` 기준으로만 설명한다.

## 산출물 구성

| 영역 | 문서 |
|---|---|
| 시스템 아키텍처 | [architecture.md](architecture.md) |
| API 레퍼런스 | [api-reference.md](api-reference.md) |
| 사일로 SDK 사용 가이드 | [silo-sdk-guide.md](silo-sdk-guide.md) |
| 운영 (실행/배포) | [operations.md](operations.md) |

## 실행 방법

### 1. 사전 요구사항
- Python 3.11+ (asyncio.to_thread, PEP 604 union 사용)
- (선택) Docker 데몬 — 패키징/배포 기능 사용 시 호스트 소켓 필요

### 2. 의존성 설치

```bash
cd app

# 런타임만
pip install -r requirements.txt

# 또는 개발/테스트/린트 도구까지 한 번에
pip install -r requirements-dev.txt
```

`requirements.txt` 내용:
- fastapi, uvicorn[standard], pydantic≥2.0, docker, Jinja2, PyYAML

`requirements-dev.txt` 추가:
- pytest, pytest-asyncio, pytest-cov, ruff

### 3. 단위 테스트 (147개)

```bash
cd app
python -m pytest tests/                          # 전체
python -m pytest tests/ -v                       # 상세
python -m pytest tests/test_drift_detector.py    # 특정 파일
python -m pytest tests/ --cov=. --cov-report=term-missing  # 커버리지
```

### 4. 서버 기동

```bash
cd app

# 개발 (자동 reload)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 운영 검증
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

접속:
- `http://localhost:8000/dashboard` — 5종 차트 통합 UI
- `http://localhost:8000/docs` — OpenAPI Swagger UI
- `http://localhost:8000/redoc` — ReDoc 문서
- `http://localhost:8000/api/monitoring/prometheus` — Prometheus exposition

대시보드 데모 데이터 주입:

```bash
cd app
python scripts/seed_demo.py --base-url http://localhost:8000

# 운영 config와 분리된 데모 디렉토리를 쓰고 싶을 때
python scripts/seed_demo.py --base-url http://localhost:8000 --demo-config --reset-demo
```

`demo-alpha@1.0.0`, 6개 데모 사일로, 리소스 샘플, 성능 메트릭,
드리프트 baseline(`feature=age`)이 주입된다.
`--demo-config`를 사용할 때는 서버도 같은 `FED_CONFIG_DIR=<repo>/config.demo`
환경으로 실행해야 servers/deployments YAML을 동일하게 바라본다.

`FED_API_KEY`로 API 보호를 켠 경우 `/dashboard` 상단의 API Key 입력칸에
같은 값을 넣으면 브라우저 요청에 `X-FED-API-Key`가 포함된다. 대시보드 하단의
운영 현황 패널은 모델, 사일로 그룹, 배포, 리소스/알림을 읽기 전용으로 보여준다.

### 5. Docker로 실행

```bash
# API Key 없이 개발 모드
docker compose -f compose.fed-platform.yaml up -d --build

# API Key 보호 활성화
FED_API_KEY=change-me docker compose -f compose.fed-platform.yaml up -d --build
```

Dockerfile은 `app/Dockerfile`, Compose 파일은 저장소 루트
`compose.fed-platform.yaml`에 있다.

운영 시 Docker 소켓 마운트는 패키징/배포 라우터(P0 #1)에만 필요하며, 모니터링/시각화/사일로 링크 기능은 소켓 없이 동작한다.

### 5.1 환경 변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `FED_CONFIG_DIR` | `<repo>/config` | YAML 영속화 디렉토리. 컨테이너에서는 `/srv/config` |
| `FED_API_KEY` | 빈 값 | 설정 시 `/api/*` 요청에 `X-FED-API-Key` 헤더 필요 |
| `FED_PLATFORM_PORT` | `8000` | Compose 호스트 포트 |

### 6. CI (선택)

`app/ci/ci.yml`을 저장소 루트 `.github/workflows/`로 복사하면 PR/push 시 자동 실행:

```bash
mkdir -p .github/workflows
cp app/ci/ci.yml .github/workflows/ci.yml
cp app/ci/ruff.toml ruff.toml
```

자세한 내용은 [app/ci/README.md](../ci/README.md) 참조.

### 7. 사일로 측 사용

사일로에서는 `app/silo_sdk/` 디렉토리만 있으면 동작 (외부 의존성 없이 stdlib만 사용):

```python
from silo_sdk import SiloClient

client = SiloClient("http://central:8000", silo_id="silo-2")
client.push_metric("alpha", "1.0.0", "accuracy", 0.93)
```

자세한 SDK 사용법은 [silo-sdk-guide.md](silo-sdk-guide.md) 참조.

## 구현된 Notion 작업 (9/9)

| 우선순위 | 작업명 | 카테고리 | 핵심 산출물 |
|---|---|---|---|
| 🔴 P0 #1 | 모델 패키징 및 배포 | 중앙플랫폼 | 컨테이너 빌드, 3가지 배포 전략, 롤백 |
| 🔴 P0 #2 | 모델 모니터링 | 중앙플랫폼 | PSI 드리프트 감지, 자동 롤백, Prometheus |
| 🟠 P1 | 사일로 링크 + 파라미터 수집 | 사일로검증 | 사일로 그룹, FedAvg 집계, 라운드 라이프사이클 |
| 🟠 P1 | Batch Scheduling 자동화 | 분할학습 | manual/chain/interval 잡, 자원 게이트 |
| 🟠 P1 | 리소스 모니터링 | 사일로검증 | CPU/메모리/GPU/디스크 임계값, 자동 알림 |
| 🟠 P1 | 모델 유지관리 | 중앙플랫폼 | lineage, 섀도우 배포, Welch t-검정 A·B |
| 🟠 P1 | 다양한 사일로 데이터 정제 | 분할학습 | 8종 step 레시피, 자동 샤딩, 분산 집계 |
| 🟡 P2 | 사일로 데이터 시각화 | 사일로검증 | 5종 차트 (공인인증 KPI 충족) |
| 🟡 P2 | 비동기 I/O 처리 | 분할학습 | asyncio.gather 병렬 컴포지션, AsyncSiloClient |

## 정량 결과

| 지표 | 값 |
|---|---|
| API 라우트 | 86개 (`/api/*`, 자동 문서 제외) |
| FastAPI 전체 라우트 | 93개 (`/`, `/dashboard`, probe, 자동 문서 포함) |
| 단위/통합 테스트 | 147개 |
| 시각화 차트 종류 | 5종 |
| YAML 영속화 도메인 | 15종 (atomic write 적용) |
| 외부 런타임 의존성 | fastapi, uvicorn, docker, jinja2, PyYAML, pydantic≥2.0 (전부 pip 표준) |

## 개인정보 보호 원칙

본 플랫폼은 다음을 **절대 위반하지 않는다** ([architecture.md](architecture.md) §보안 참조):

1. 사일로의 원시 데이터는 중앙으로 전송되지 않는다.
2. 사일로↔중앙 통신은 메트릭(스칼라), 분포 통계(히스토그램 카운트), 모델 파라미터 벡터에 한정된다.
3. 데이터 정제는 사일로 내부에서만 수행되며, 결과 **카운터**만 보고된다.

## 디렉토리 구조

```
app/
├── main.py                    # FastAPI 진입점 (lifespan + router/probe)
├── api/                       # 19개 라우터 모듈
├── services/                  # 27개 서비스 모듈 + Jinja 템플릿
├── models/                    # 9개 Pydantic 스키마 모듈
├── config/                    # YAML 영속화 (15종)
├── silo_sdk/                  # 사일로용 push 클라이언트 (sync + async)
├── scripts/                   # 데모/운영 보조 스크립트
├── tests/                     # 147개 pytest (asyncio mode=auto)
├── docs/                      # 본 디렉토리
└── pytest.ini
```
