# 운영 가이드

> **런타임 통합 기동 순서**는 [runbook.md](./runbook.md) 참조 (silo → fed-platform → probe).

## 실행

### 로컬 (개발)
```bash
cd app
pip install fastapi 'uvicorn[standard]' docker jinja2 'PyYAML>=6.0' 'pydantic>=2.0'
pip install pytest pytest-asyncio

# 테스트
python -m pytest tests/

# 서버 기동
uvicorn main:app --host 0.0.0.0 --port 8000

# API Key 보호 활성화
$env:FED_API_KEY="change-me"
uvicorn main:app --host 0.0.0.0 --port 8000

# probe 확인
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

대시보드가 비어 있으면 데모 데이터를 주입할 수 있다.

```bash
python scripts/seed_demo.py --base-url http://localhost:8000

# 운영 config와 분리된 데모 디렉토리 사용
python scripts/seed_demo.py --base-url http://localhost:8000 --demo-config --reset-demo
```

`--demo-config`를 사용할 때는 서버도 같은 `FED_CONFIG_DIR=<repo>/config.demo`
환경으로 실행해야 servers/deployments YAML을 동일하게 바라본다.

### Docker
```bash
docker compose -f compose.fed-platform.yaml up -d --build

# API Key 보호 활성화
FED_API_KEY=change-me docker compose -f compose.fed-platform.yaml up -d --build
```

Docker 데몬 제어가 필요하므로 호스트 socket을 마운트:
```bash
docker run -d \
  -p 8000:8000 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v $(pwd)/config:/srv/config \
  fed-platform
```

## 디렉토리 / 파일

| 위치 | 용도 |
|---|---|
| `app/main.py` | FastAPI 진입점 (uvicorn 타깃) |
| `app/Dockerfile` | 루트 `app/` 컨테이너 이미지 정의 |
| `compose.fed-platform.yaml` | 루트 플랫폼 Compose 실행 정의 |
| `app/pytest.ini` | pytest 설정 (`asyncio_mode=auto`) |
| `app/scripts/seed_demo.py` | `/dashboard` 검증용 6개 사일로 데모 데이터 주입 |
| `app/scripts/migrate_yaml_to_sqlite.py` | YAML → SQLite 일회성 import |
| `config/` | YAML 영속화 (`settings.py:CONFIG_DIR`) — 컨테이너 외부 볼륨 권장 |
| `config/fed_platform.db` | SQLite 백엔드 사용 시 DB (기본 경로, 아래 참조) |
| `app/storage/` | Repository 인터페이스, YAML/SQLite 백엔드, 마이그레이션 |
| `app/services/templates/` | Dockerfile + Helm Chart 템플릿 (이미지 빌드 시 사용) |

## 저장소 백엔드 (YAML / SQLite)

기본값은 **YAML** (`FED_STORAGE=yaml`)이며, 기존 배포·테스트와 동일하게 동작한다.
다중 프로세스·감사 이력이 필요하면 **SQLite**로 전환한다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `FED_STORAGE` | `yaml` | `yaml` 또는 `sqlite` (권장) |
| `FED_STORAGE_BACKEND` | — | `FED_STORAGE`와 동일; 하위 호환 별칭 |
| `FED_SQLITE_PATH` | `<FED_CONFIG_DIR>/fed_platform.db` | SQLite 파일 절대/상대 경로 |

**경로 정책**

- `FED_CONFIG_DIR`: YAML 파일·감사 로그·(기본) SQLite가 함께 두는 루트 디렉토리.
- `FED_SQLITE_PATH`를 설정하면 DB만 별도 디스크/볼륨에 둘 수 있다 (YAML은 `FED_CONFIG_DIR` 유지).
- SQLite는 WAL 모드 + `BEGIN IMMEDIATE` 트랜잭션으로 동시 쓰기를 완화한다.

**마이그레이션**

```bash
cd app
# YAML이 있는 config 디렉토리를 SQLite로 import
FED_CONFIG_DIR=../config python scripts/migrate_yaml_to_sqlite.py

# 이후 서버를 SQLite 백엔드로 기동
FED_STORAGE=sqlite FED_CONFIG_DIR=../config uvicorn main:app --host 0.0.0.0 --port 8000
```

import 대상: `models`, `deployments`, `silo_groups`, `training_rounds`, `resource_limits`, `alerts`.
메트릭 시계열은 기본적으로 인메모리(`metric_store`)이며, DB 테이블은 마이그레이션 시 선택적 스냅샷용이다.

## 환경 변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `FED_CONFIG_DIR` | `<repo>/config` | YAML/SQLite(기본) 영속화 디렉토리. 컨테이너에서는 `/srv/config` |
| `FED_STORAGE` | `yaml` | `sqlite` 시 Repository가 DB를 사용 (`FED_STORAGE_BACKEND` 별칭 가능) |
| `FED_SQLITE_PATH` | `<FED_CONFIG_DIR>/fed_platform.db` | SQLite 파일 위치 |
| `FED_API_KEY` | 빈 값 | 설정 시 `/api/*` 요청에 `X-FED-API-Key` 헤더 필요 |
| `FED_PLATFORM_PORT` | `8000` | Compose 호스트 포트 |

사일로 SDK도 동일한 API Key를 지원한다.

```python
from silo_sdk import SiloClient

client = SiloClient("http://central:8000", "silo-1", api_key="change-me")
```

브라우저 대시보드는 상단 API Key 입력칸 값을 `sessionStorage`에 보관하고
`/api/*` 요청에 `X-FED-API-Key` 헤더로 붙인다. 같은 화면의 운영 현황 패널은
모델, 사일로 그룹, 배포, 리소스/알림 상태를 읽기 전용으로 집계한다.

## 모니터링 외부 연동

### Prometheus + Grafana
`GET /api/monitoring/prometheus` → Prometheus exposition 텍스트.

`prometheus.yml` 예시:
```yaml
scrape_configs:
  - job_name: fed-platform
    metrics_path: /api/monitoring/prometheus
    static_configs:
      - targets: ['central:8000']
```

Grafana에서 Prometheus 데이터 소스로 추가 후 다음 메트릭 사용 가능:
- `fed_model_accuracy{model,version,node}`
- `fed_model_latency_ms{model,version,node}`
- `fed_model_throughput_rps{model,version,node}`

## 백업 / 복구

### YAML 백엔드
`config/` 디렉토리를 통째로 백업한다. YAML 저장은 같은 디렉토리에 임시 파일을 만든 뒤
`os.replace`로 교체하는 atomic write 방식이다. 다중 uvicorn 워커 간 쓰기 직렬화는
보장하지 않으므로 YAML 운영 시 단일 워커를 권장한다.

```bash
tar czf fed-config-$(date +%Y%m%d).tgz config/
```

### SQLite 백엔드
`fed_platform.db`와 동일 디렉토리의 `fed_platform.db-wal`, `fed_platform.db-shm`을
함께 백업한다. 애플리케이션 API(`storage.sqlite_store.backup_database`) 또는:

```bash
sqlite3 config/fed_platform.db "PRAGMA wal_checkpoint(FULL);"
cp config/fed_platform.db config/fed_platform.db.bak
```

복구: 백업 파일을 원래 경로에 복사 후 `FED_STORAGE_BACKEND=sqlite`로 재기동.
YAML 백엔드로 롤백할 경우 `FED_STORAGE_BACKEND=yaml`만 변경하면 된다 (YAML 파일이 남아 있으면).

## 보안 체크리스트

- [ ] 사일로 ↔ 중앙 통신은 TLS 종단 (uvicorn `--ssl-certfile` / 리버스 프록시)
- [ ] Docker 데몬 소켓 마운트 (`/var/run/docker.sock`)는 인증된 컨테이너에만 노출
- [ ] `config/` YAML 파일은 OS 권한으로 보호 (running user only)
- [ ] 본 플랫폼은 인증 미내장 — 외부 노출 금지 (내부망 전용)
- [ ] 사일로 측은 정제된 데이터/원시 데이터를 SDK 호출로 push하지 않도록 사용 코드 코드 리뷰 의무화

## 트러블슈팅

| 증상 | 원인 후보 | 대응 |
|---|---|---|
| `/api/packaging/build` 실패 | 호스트 Docker socket 미마운트 | 컨테이너 실행 시 `-v /var/run/docker.sock:/var/run/docker.sock` |
| Batch 잡이 라운드를 안 연다 | 그룹 멤버 자원 압박 또는 `max_concurrent_rounds` 도달 | `GET /api/resources/usage` 확인, 임계값 조정 또는 잡 정리 |
| A·B 평가 inconclusive | min_samples_per_arm 미충족 또는 \|t\| < threshold | 더 많은 메트릭 누적 후 재평가 |
| 시각화 endpoint가 None/빈 시리즈 | 사일로 push 미수신 | SDK 호출 코드 점검 |
| 드리프트 항상 critical | 베이스라인이 너무 좁거나 bin이 부족 | `set_baseline`을 더 대표성 있는 분포로 재설정 |

## 리소스 알림 임계값 정책

`resource_service.set_limit(ResourceLimit)`로 사일로별 **백분율 상한**을 등록한다.
CPU·메모리·GPU·디스크는 각각 독립 평가되며, **한 샘플에서 여러 메트릭이 동시에** 초과하면
알림이 복수 발화된다 (`ResourceAlert` per metric).

| 정책 | 동작 |
|------|------|
| 비교 연산 | `observed > cap` (strict greater-than) |
| cap 미설정 (`null`) | 해당 메트릭은 평가 생략 |
| GPU/Disk `null` in sample | 해당 축 스킵 |
| 샘플 보존 | 사일로당 최근 500건 (인메모리, 재시작 시 소멸) |
| Batch 게이트 | `is_silo_available()` — **최신 샘플**이 모든 등록 cap 이하일 때만 true |
| 그룹 게이트 | `group_has_pressure()` — 멤버 중 하나라도 unavailable이면 라운드 보류 |

**운영 권장**

- CPU/메모리: 80–85% warning, 90%+ 운영 cap (워크로드에 따라 조정)
- GPU: 학습 잡이 없는 사일로는 cap을 `null`로 두어 불필요 알림 방지
- Disk: 85% cap + 외부 Prometheus/Grafana 장기 추세 병행
- 임계값 변경 후 `GET /api/resources/alerts?active_only=true`로 발화 확인

알림은 감사 로그(`audit.log`)에 `resource_alert` 이벤트로 기록된다.
자세한 API는 [api-reference.md](./api-reference.md) 및 [traceability.md](./traceability.md) 참조.

## 테스트 실행

```bash
cd app

# 전체
python -m pytest tests/

# 저장소 레이어 (Repository / migration / backup)
python -m pytest tests/test_storage_repository.py -q

# 특정 도메인
python -m pytest tests/test_drift_detector.py tests/test_alert_service.py

# 커버리지 (pytest-cov 별도 설치)
pip install pytest-cov
python -m pytest tests/ --cov=. --cov-report=term-missing --cov-report=html
```
