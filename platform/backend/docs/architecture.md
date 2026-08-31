# 시스템 아키텍처

## 1. 개요

본 플랫폼은 **다수의 사일로(Silo)** 환경에서 학습된 모델을 중앙(Aggregator) 서버가 통합·배포·모니터링하는 연합학습(FL) 인프라이다.
중앙은 FastAPI 기반 단일 ASGI 애플리케이션이며, 사일로는 경량 Python SDK(`silo_sdk`)로 중앙과 통신한다.

```
        ┌─────────────────────────────────────┐
        │  중앙 대시보드  (FastAPI / uvicorn)    │
        │  ───────────────────────────────────  │
        │  • 모델 레지스트리 + 패키징/배포        │
        │  • 메트릭 수집 + 드리프트 감지         │
        │  • 학습 라운드 + Batch 스케줄러        │
        │  • 리소스/알림/감사 로그              │
        │  • lineage / shadow / A·B            │
        │  • 데이터 정제 잡 오케스트레이션        │
        │  • 5종 시각화 + 통합 대시보드 API     │
        └──────────────────▲──────────────────┘
                           │  HTTP (push only)
        ┌──────────────────┴──────────────────┐
        │             사일로 N개              │
        │  ───────────────────────────────────  │
        │  • silo_sdk.SiloClient (sync/async)  │
        │  • 로컬 학습 / 로컬 정제              │
        │  • 통계·파라미터·리소스만 push        │
        │  • 원시 데이터는 절대 외부 유출 ❌      │
        └─────────────────────────────────────┘
```

## 2. 계층 구조

| 계층 | 위치 | 역할 |
|---|---|---|
| API | `app/api/*.py` | HTTP 라우터 — 19개 모듈, 91 엔드포인트 |
| Service | `app/services/*.py` | 비즈니스 로직 — Strategy, FedAvg, PSI, Welch t, 잡 오케스트레이션 |
| Schema | `app/models/*.py` | Pydantic v2 DTO + 검증 |
| Storage | `app/config/*.py` | YAML 영속화 헬퍼 (process-local) |
| SDK | `app/silo_sdk/` | 사일로 측 push 클라이언트 (stdlib only, sync + async) |

## 3. 9개 작업별 설계

### 3.1 P0 #1 — 모델 패키징 및 배포

**핵심 흐름**:
1. 모델 등록 → `services/model_registry.py` (SemVer 검증, YAML 영속화)
2. Docker 이미지 빌드 → `services/packaging_service.py`
   * Jinja2로 `Dockerfile.inference.j2`, `inference_server.py.j2` 렌더
   * `docker.from_env().images.build()` (host Docker socket 사용)
3. 배포 → `services/deployment_service.py` + Strategy 패턴 (`deployment_strategies.py`)
   * `realtime` — autostart + restart=always
   * `batch` — created 상태 유지, 라벨 `fed.batch=pending`
   * `edge` — role=client 노드만, restart=unless-stopped
4. 롤백 → `previous_deployment_id` 체인 활용

**산출물 외부 연동**:
- Helm Chart: `services/templates/helm/` (deployment.yaml + service.yaml + readiness/liveness probe)
- 추론 서버: 자동 생성 FastAPI 앱 (`/health`, `/meta`, `/predict`)

### 3.2 P0 #2 — 모델 모니터링

**핵심 흐름**:
1. 사일로 → 중앙 push: 메트릭(`MetricIngest`) + 분포 통계(`DistributionStats`, 히스토그램만)
2. 인메모리 시계열 저장: `metric_store.py` (thread-safe rolling window, 1000개/키)
3. 드리프트 감지: `drift_detector.py` — Population Stability Index
   ```
   PSI = Σ (a% - e%) × ln(a% / e%)
   < 0.10: stable / < 0.25: warning / ≥ 0.25: critical
   ```
4. 알림: `alert_service.py` — 규칙 평가 + 자동 롤백 훅 + 재교육 트리거
5. Prometheus exposition: `/api/monitoring/prometheus` (Grafana 데이터 소스 직접 연결)

**개인정보 보호**:
- `DistributionStats.bin_counts`는 정수 카운트만, 원시 샘플 필드 부재
- `compute_psi(expected_counts, actual_counts)`는 정수 배열만 입력

### 3.3 P1 — 사일로 링크 + 파라미터 수집

**핵심 흐름**:
1. 사일로 그룹 정의: `silo_group_service.py` — servers.yaml과 join
2. 학습 라운드 라이프사이클: `training_round_service.py`
   * status: `open` → `aggregating` → `completed`/`failed`
   * thread-safe 동시 기여 처리 (`_round_lock`)
3. FedAvg 집계: `fedavg_aggregator.py`
   ```
   θ_global = Σ (n_k / N) × θ_k     # n_k: 사일로 k 표본수
   ```
4. 백그라운드 자동 집계: `round_scheduler.py` (FastAPI lifespan + asyncio.Task)

### 3.4 P1 — Batch Scheduling 자동화

**스케줄 종류** (`training_job_service.py`):
- `manual` — 자동 진행 없음
- `chain` — 이전 라운드 완료 직후 다음 라운드
- `interval` — 이전 라운드 완료 + N초 경과 후 다음 라운드

**자원 의존성** (Notion 메모 충족):
- 그룹 멤버 중 한 노드라도 임계값 초과 → 라운드 보류 (`resource_service.group_has_pressure`)
- 동시 라운드 한도: `max_concurrent_rounds` (기본 3)

### 3.5 P1 — 리소스 모니터링

**자원 종류**: CPU / Memory / GPU / Disk (nullable, 0~100 백분율)

**동작**:
1. 사일로 SDK push → `resource_service.ingest_sample`
2. 임계값 평가 → `ResourceAlert` 발화 (메트릭별 다중 동시 발화 가능)
3. Batch 스케줄러가 `is_silo_available()` 호출 → 자원 게이트

### 3.6 P1 — 모델 유지관리

**3개 컴포넌트**:
1. **lineage**: 버전 간 부모-자식 관계 (`ModelLineage` — parent_version, change_type, change_notes, derived_from_round_id)
2. **shadow_deployment**: primary 옆 짝 배포 + traffic_mirror_pct 메타데이터
   - promote: 섀도우를 primary로, 기존 primary 정지
   - abort: 섀도우만 정지, primary 유지
3. **ab_test**: Welch 두-표본 t-검정 (등분산 가정 없음)
   ```
   t = (μ_a - μ_b) / √(σ_a²/n_a + σ_b²/n_b)
   |t| ≥ significance_threshold → 승자 결정 (higher_is_better 기반)
   ```

### 3.7 P1 — 사일로 데이터 정제

**8종 step 카탈로그** (`services/cleaning_recipes.py`):
- drop_nulls, clip_outliers, dedupe, cast, normalize, trim_whitespace, lowercase, regex_filter

**분산 처리 모델**:
- 그룹 멤버 N개 → 자동 샤드 N개 (1:1 매핑)
- 사일로 SDK: `silo_sdk.apply_recipe()` 로컬 적용 → 카운터만 보고
- 중앙: 모든 샤드 보고 시 자동 집계 (`_maybe_finalize`)
- 상태: pending → running → completed/partial/failed

### 3.8 P2 — 사일로 데이터 시각화 (공인인증 KPI)

**5종 차트**:
1. timeseries — 메트릭 추이 (사일로별 시리즈)
2. histogram — 분포 (드리프트 베이스라인)
3. silo_bar — 사일로 간 비교 (리소스/라운드 기여)
4. heatmap — 사일로 × 메트릭 격자
5. topology — 그룹/배포/노드 그래프 + over_budget 플래그

**Notion 공인인증 KPI 충족**:
- 시각화 5종 ✅
- 사일로 6개 동시 측정 검증 (`test_silo_bar_resource_returns_6_silos`)

### 3.9 P2 — 비동기 I/O

**전략**:
- `services/async_io.py` — `asyncio.to_thread` 기반 (외부 의존성 없이 stdlib만)
- `api/dashboard.py` — 5종 차트를 `asyncio.gather`로 병렬 컴포지션
- `silo_sdk/async_client.py` — `AsyncSiloClient.push_many_metrics()` 다중 push 동시 처리
- 부분 실패 격리: `gather_calls_safe(return_exceptions=True)`

## 4. 데이터 흐름

### 4.1 FL 라운드 (정상 경로)
```
사일로(로컬 학습) ──push parameters──▶ 라운드(open)
                                          │
                       (모든 사일로 기여 후)
                                          ▼
              스케줄러 tick ──aggregate──▶ FedAvg ──▶ 라운드(completed)
                                                       │
                                                       ▼
                                              잡 reconcile + 다음 라운드 open
```

### 4.2 모니터링 + 자동 롤백
```
사일로 ──push metric──▶ alert_service.evaluate_metric
                          │
                          ▼
                    임계값 위반 + auto_rollback=true
                          │
                          ▼
                deployment_service.rollback_deployment
                          │
                          ▼
                  이전 배포로 자동 복원
```

### 4.3 정제 잡
```
중앙(잡 생성) ──샤드 자동 배정──▶ N개 사일로
                                    │
                                    ▼
            silo_sdk.apply_recipe (로컬 적용)
                                    │
                                    ▼
            push 통계만 ──▶ 중앙 reconcile ──▶ 잡 status 자동 갱신
```

## 5. 동시성 모델

| 구성요소 | 동시성 |
|---|---|
| FastAPI 핸들러 | 비동기 (uvicorn ASGI) |
| metric_store | `threading.Lock` (in-memory rolling window) |
| training_round_service | `threading.Lock` (기여 등록/집계) |
| resource_service | `threading.Lock` (샘플 ingest) |
| training_job_service | `threading.Lock` (tick 단일 진입) |
| RoundScheduler | `asyncio.Task` + `asyncio.Event` 종료 신호 |
| 모든 to_thread 호출 | 차단 I/O를 스레드풀로 위임 |

## 6. 영속화 모델

각 도메인은 독립 YAML 파일에 보관. 경로는 `config/settings.py:CONFIG_DIR` 기준 상대.

| 파일 | 도메인 |
|---|---|
| servers.yaml | 노드/사일로 |
| models.yaml | 모델 레지스트리 |
| deployments.yaml | 배포 기록 |
| baselines.yaml | 드리프트 베이스라인 |
| alert_rules.yaml, alerts.yaml | 알림 |
| audit.log | JSON Lines 감사 로그 |
| silo_groups.yaml | 사일로 그룹 |
| training_rounds.yaml, contributions.yaml | 학습 라운드 |
| training_jobs.yaml | Batch 잡 |
| resource_limits.yaml | 리소스 임계값 |
| lineage.yaml, shadow_deployments.yaml, ab_tests.yaml | 유지관리 |
| cleaning_recipes.yaml, cleaning_jobs.yaml | 정제 |

## 7. 보안 / 개인정보

### 7.1 데이터 흐름 제약

| 통신 항목 | 사일로 → 중앙 | 비고 |
|---|---|---|
| 모델 파라미터 벡터 | ✅ 허용 | 가중치만 |
| 메트릭 (스칼라) | ✅ 허용 | accuracy / latency / throughput |
| 분포 통계 | ✅ 허용 (히스토그램 카운트만) | 원시 샘플 없음 |
| 리소스 사용률 (백분율) | ✅ 허용 | |
| 정제 카운터 | ✅ 허용 | rows_in, rows_out, step별 affected |
| **원시 데이터** | ❌ **절대 금지** | 스키마 자체에 필드 부재 |

### 7.2 스키마 강제

- `MetricIngest.value: float` — 스칼라만
- `DistributionStats.bin_counts: list[int]` — 정수 카운트
- `ShardReport`: rows_in/out/step_counters 만, 데이터 페이로드 필드 부재

### 7.3 추후 보강

- TLS (Notion `CLAUDE.md`의 "통신 암호화" 요구) — 운영 시 uvicorn `--ssl-keyfile` 옵션
- 인증/인가 — 현 코드에는 미구현 (CLAUDE.md 명시 "내부 R&D 컨벤션, 외부 노출 금지")

## 8. 자체 브랜드 플랫폼 및 오픈소스 은닉화 가이드 (White-Label Architecture)

본 플랫폼은 **독자 개발된 자체 브랜드 플랫폼(Proprietary Web Portal)**으로서의 고유한 가치와 룩앤필(Look and Feel)을 유지하기 위해, 하단의 오픈소스 엔진 및 가상화 인프라의 날것의 UI 노출을 철저히 차단하고 은닉하는 **화이트라벨 아키텍처(White-Label Architecture)**를 준수한다.

### 8.1 4대 은닉 및 우회 설계 규칙

1. **오픈소스 UI 직접 노출 차단 (iframe 사용 금지)**:
   * Prometheus UI, Portainer, MinIO Console 등 타사 및 오픈소스의 기본 제어 웹 화면을 iframe이나 직접 하이퍼링크 형식으로 플랫폼 전면에 노출하는 것을 일절 금지한다.
2. **API 기반 데이터 추출 및 자체 차트 투사**:
   * 오픈소스 인프라는 순수한 **데이터 프로바이더(Data Provider)** 엔진으로만 백스테이지에서 가동한다.
   * 백엔드 API Gateway가 내부 Prometheus PromQL 및 Docker SDK를 호출하여 알맹이 데이터(JSON)만 추출한 뒤, 자체 개발한 프론트엔드 UI의 빌트인 차트 컴포넌트(Chart.js / Apache ECharts 등)를 거쳐 고유한 네온 다크 테마 디자인으로 투사한다.
3. **단일 API 게이트웨이 은닉화**:
   * 오픈소스 서버들의 포트(예: Prometheus `9090`, MinIO `9001`)는 외부 방화벽으로 철저히 차단한다.
   * 오직 단일 자체 게이트웨이(예: 당사 FastAPI `8010` 포트)의 가공된 엔드포인트(`/api/v1/...`)를 통해서만 통신을 허용하여 단일화된 보안 채널을 유지한다.
4. **브랜드 테마 오버라이딩 (Theme Overriding)**:
   * 오픈소스 프론트엔드 라이브러리를 사용하더라도 외곽 브랜딩 스타일, 네온 HSL 변수(`--accent`, `--ok`, `--danger`) 및 곡률(Border Radius `20px`)을 오버라이딩하여, 사용자로 하여금 완벽하게 일치된 당사 고유 기술 플랫폼으로 경험하게 유도한다.

