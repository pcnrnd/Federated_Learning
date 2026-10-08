# API 레퍼런스

> 전체 91개 엔드포인트. OpenAPI/Swagger UI: `http://host:8000/docs`

## 모델 레지스트리 (P0 #1)

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/models` | 등록된 모든 모델 버전 |
| POST | `/api/models` | 신규 버전 등록 (SemVer) |
| GET | `/api/models/{name}/versions` | 특정 모델의 버전 목록 (최신순) |
| GET | `/api/models/{name}/latest` | SemVer 최신 |
| GET | `/api/models/{name}/{version}` | 단건 조회 |
| DELETE | `/api/models/{name}/{version}` | 제거 |

## 패키징 (P0 #1)

| Method | Path | 설명 |
|---|---|---|
| POST | `/api/packaging/build` | Docker 이미지 빌드 |
| POST | `/api/packaging/dockerfile` | Dockerfile 텍스트만 렌더 (드라이런) |

## 배포 (P0 #1)

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/deployments` | 모든 배포 기록 |
| POST | `/api/deployments` | 새 배포 (realtime / batch / edge) |
| GET | `/api/deployments/{id}` | 단건 |
| POST | `/api/deployments/{id}/stop` | 정지/제거 |
| POST | `/api/deployments/{id}/rollback` | 이전 배포로 1-click 롤백 |

## 모니터링 (P0 #2)

| Method | Path | 설명 |
|---|---|---|
| POST | `/api/monitoring/metrics` | 메트릭 단일 샘플 수집 |
| GET | `/api/monitoring/metrics` | 필터링 조회 |
| GET | `/api/monitoring/summary` | accuracy/latency/throughput 집계 |
| POST | `/api/monitoring/baselines` | 드리프트 기준 분포 등록 |
| GET | `/api/monitoring/baselines` | 기준 분포 목록 (`model_name`·`version` 선택 필터, 분포 값 제외) |
| POST | `/api/monitoring/drift` | PSI 평가 + 자동 알림/재교육 트리거 |
| POST | `/api/monitoring/rules` | 알림 규칙 upsert |
| GET | `/api/monitoring/rules` | 규칙 목록 |
| DELETE | `/api/monitoring/rules/{id}` | 규칙 제거 |
| GET | `/api/monitoring/alerts` | 알림 인스턴스 |
| POST | `/api/monitoring/alerts/{id}/ack` | ACK |
| GET | `/api/monitoring/audit` | 감사 로그 tail |
| GET | `/api/monitoring/retrain-triggers` | 재교육 트리거 조회 |
| GET | `/api/monitoring/prometheus` | Prometheus exposition |

`GET /api/monitoring/baselines`는 신규 등록 레코드에 `model_name`·`version`·`feature`를 함께 저장해 정확히 목록화한다. 해당 필드가 없는 기존 레코드는 키를 오른쪽부터 분해하므로, `feature`에 `::`가 든 기존 레코드는 식별자가 틀릴 수 있다(알려진 한계).

## 사일로 그룹 (P1)

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/silo-groups` | 모든 그룹 |
| POST | `/api/silo-groups` | 신규 그룹 |
| GET | `/api/silo-groups/{group_id}` | 단건 |
| PUT | `/api/silo-groups/{group_id}` | 갱신 |
| DELETE | `/api/silo-groups/{group_id}` | 제거 |
| GET | `/api/silo-groups/{group_id}/members` | servers.yaml과 join한 멤버 정보 |

## 학습 라운드 (P1)

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/training-rounds` | 모든 라운드 (필터: model/group/status) |
| POST | `/api/training-rounds` | 새 라운드 |
| GET | `/api/training-rounds/{id}` | 단건 |
| POST | `/api/training-rounds/{id}/contributions` | 사일로 파라미터 기여 |
| GET | `/api/training-rounds/{id}/contributions` | 기여 목록 |
| POST | `/api/training-rounds/{id}/aggregate` | FedAvg 집계 |

기여에 정제 통계를 함께 보낼 수 있다(선택): `rows_before_cleaning`·`rows_after_cleaning`·
`train_rmse` — 사일로가 레시피로 정제한 로컬 데이터로 학습했을 때의 행 수와 학습 오차다.
라운드의 `cleaning_stats`(사일로별)와 기여 목록에 기록된다. 생략하면 기존과 같다.

라운드·잡 생성 시 `cleaning_job_id`(선택, 없는 작업이면 404)로 학습 입력을 만든 정제 작업을
기록한다. 잡이 여는 라운드에 그대로 이어지고, 사일로 `train-loop`는 레시피를 따로 주지 않으면
라운드에 연결된 정제 작업의 레시피로 로컬 원천을 정제해 학습한다.

## Batch 잡 (P1)

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/training-jobs` | 모든 잡 |
| POST | `/api/training-jobs` | 새 잡 (schedule: manual/chain/interval) |
| GET | `/api/training-jobs/{id}` | 단건 |
| POST | `/api/training-jobs/{id}/pause` | 일시정지 |
| POST | `/api/training-jobs/{id}/resume` | 재개 |
| POST | `/api/training-jobs/{id}/cancel` | 취소 |
| POST | `/api/training-jobs/_tick` | 수동 tick (디버그용) |

## 리소스 (P1)

| Method | Path | 설명 |
|---|---|---|
| POST | `/api/resources/limits` | 사일로별 임계값 설정 |
| GET | `/api/resources/limits` | 모든 임계값 |
| GET | `/api/resources/limits/{silo_id}` | 단건 |
| DELETE | `/api/resources/limits/{silo_id}` | 제거 |
| POST | `/api/resources/samples` | 리소스 샘플 수집 |
| GET | `/api/resources/samples/{silo_id}` | 샘플 시계열 |
| GET | `/api/resources/usage` | 모든 사일로 latest + over_budget 플래그 |
| GET | `/api/resources/alerts` | 임계값 위반 알림 |

## 모델 유지관리 (P1)

### lineage
| Method | Path | 설명 |
|---|---|---|
| PUT | `/api/lineage/{name}/{version}` | 부모/변경 기록 등록 |
| GET | `/api/lineage/{name}/{version}` | 단건 |
| GET | `/api/lineage/{name}/tree/` | lineage 트리 |
| GET | `/api/lineage/{name}/{version}/ancestors` | 조상 체인 |

### shadow deployment
| Method | Path | 설명 |
|---|---|---|
| GET | `/api/shadow-deployments` | 모든 섀도우 |
| POST | `/api/shadow-deployments` | 신규 섀도우 짝 배포 |
| GET | `/api/shadow-deployments/{id}` | 단건 |
| POST | `/api/shadow-deployments/{id}/promote` | 섀도우 → primary 승격 |
| POST | `/api/shadow-deployments/{id}/abort` | 섀도우 폐기 |

### A·B 테스트
| Method | Path | 설명 |
|---|---|---|
| GET | `/api/ab-tests` | 모든 테스트 |
| POST | `/api/ab-tests` | 새 테스트 (control/treatment) |
| GET | `/api/ab-tests/{id}` | 단건 |
| POST | `/api/ab-tests/{id}/evaluate` | Welch t-검정 실행 |
| POST | `/api/ab-tests/{id}/promote` | 승자 자동 promote/abort |
| POST | `/api/ab-tests/{id}/abort` | 강제 중단 |

## 데이터 정제 (P1)

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/cleaning-recipes` | 모든 레시피 |
| POST | `/api/cleaning-recipes` | 신규 레시피 등록 (SemVer) |
| GET | `/api/cleaning-recipes/{name}/versions` | 버전 목록 |
| GET | `/api/cleaning-recipes/{name}/{version}` | 단건 |
| DELETE | `/api/cleaning-recipes/{name}/{version}` | 제거 |
| GET | `/api/cleaning-jobs` | 모든 잡 |
| POST | `/api/cleaning-jobs` | 새 잡 (자동 샤드 배정) |
| GET | `/api/cleaning-jobs/{id}` | 단건 |
| POST | `/api/cleaning-jobs/{id}/shards/{shard_index}/start` | 샤드 처리 시작 |
| POST | `/api/cleaning-jobs/{id}/shards/{shard_index}/report` | 샤드 결과 보고 (`schema_fingerprint` 선택) |
| GET | `/api/cleaning-jobs/{id}/schema-consistency` | 사일로 간 공통 스키마 지문 일치 판정 |
| GET | `/api/cleaning-shards?silo_id=&status=` | 사일로에 배정된 샤드 (작업 번호 없이 대기 샤드 찾기) |

레시피의 `mapping`(매핑표)은 다원천 단계(`map_schema`·`union_sources`·`join_sources` 등)에
필요하다 — 공통 스키마(형식·허용 범위), 원천별 컬럼 대응, 단위 배율·오프셋, 코드표.
`schema_fingerprint`는 정제 결과의 정렬된 `컬럼:형식`을 이은 문자열의 sha256이다(값 없음).

## 사일로 간 수직 정렬 (HMAC 교집합)

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/alignment-jobs` | 모든 정렬 작업 |
| POST | `/api/alignment-jobs` | 새 작업 (`alignment_id`, 참여 `silo_ids` 2곳 이상) |
| GET | `/api/alignment-jobs/{id}` | 상태(waiting/ready)·사일로별 제출·남은·제외 수·교집합 크기·순서 일치 |
| POST | `/api/alignment-jobs/{id}/submit` | 사일로의 HMAC-SHA256 다이제스트 목록 (64자 hex만, 사일로당 1회) |
| GET | `/api/alignment-jobs/{id}/intersection?silo_id=` | 교집합 다이제스트(정렬) — 참여자만, 모두 제출 전 409 |
| POST | `/api/alignment-jobs/{id}/report` | 정렬 결과 통계(`matched`·`excluded`·`order_digest`) |

서버는 원본 id를 받지 않는다(형식 검사로 거부). 공유 키 `FED_ALIGN_KEY`는 사일로 환경변수에만
있다. 한계와 강화 방향은 `silo-sdk-guide.md` §사일로 간 수직 정렬 참조.

## 시각화 (P2)

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/visualizations` | 차트 카탈로그 (유형 5종, 엔드포인트 7개) |
| GET | `/api/visualizations/timeseries` | 메트릭 시계열 |
| GET | `/api/visualizations/histogram` | 분포 히스토그램 |
| GET | `/api/visualizations/silo-bar/resource` | 사일로별 리소스 |
| GET | `/api/visualizations/silo-bar/round` | 라운드 기여 |
| GET | `/api/visualizations/heatmap` | 사일로 × 메트릭 격자 |
| GET | `/api/visualizations/heatmap/participation` | 사일로 × 라운드 참여 매트릭스 (`group_id` 선택, `limit` 1~100·기본 20) |
| GET | `/api/visualizations/topology` | 그룹/집계자/배포 토폴로지 |

### 참여 매트릭스 (`/heatmap/participation`)

최근 `limit`개 라운드를 오래된 → 최근 순으로 열에 놓는다. 라운드가 없으면 빈 배열.
`payload`는 `HeatmapData`에 `col_meta`(라운드 id·상태·생성 시각·그룹)와 `cell_status`를 더한 형태다.

| `cell_status` | 의미 | `matrix` 값 |
|---|---|---|
| `contributed` | 라운드에 직접 기여 | `sample_count` (집계자는 자신 + 하위 합계) |
| `via_aggregator` | 다른 사일로 기여의 `aggregated_from`에 포함 | `null` |
| `missing` | `completed`·`failed` 라운드의 멤버인데 기여 없음 | `null` |
| `pending` | `open`·`aggregating` 라운드의 멤버, 아직 기여 없음 | `null` |
| `not_member` | 그 라운드의 멤버 아님 | `null` |

판정 순서는 위 표 순서다. 라운드 멤버 = `member_snapshot`(없으면 현재 그룹 멤버) ∪ 스냅샷 안 집계자가 맡은 클러스터 멤버 ∪ 실제 `aggregated_from`.
클러스터 멤버는 라운드 생성 시 기록한 `cluster_snapshot`(집계자 → 멤버)을 쓰고, 스냅샷이 없는 이전 라운드만 **현재 그룹 설정으로 추정**한다.

### 토폴로지 (`/topology`)

간선 `kind`: `group`(그룹 → 멤버), `aggregation`(집계자 → 클러스터 멤버, `metadata.group_id`), `deployment`(실행 중 배포 → 사일로).
노드 `role`: `central`, `client`, `aggregator`(엣지 클러스터 집계자), `group`, `deployment`.

## 대시보드 통합 (P2)

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/dashboard` | 5종 차트 병렬 컴포지션 (asyncio.gather) |

## 페이로드 예시

### 모델 등록
```http
POST /api/models
Content-Type: application/json

{
  "name": "alpha",
  "version": "1.0.0",
  "framework": "pytorch",
  "weights_path": "/data/alpha_v1.pt",
  "metadata": {"trained_on": "2026-05-10"}
}
```

### 배포 (3가지 전략 중 선택)
```http
POST /api/deployments
{
  "model_name": "alpha",
  "version": "1.0.0",
  "strategy": "realtime",
  "target_node_ids": ["silo-1", "silo-2"]
}
```

### 분포 통계 push (개인정보 보호: 카운트만)
```http
POST /api/monitoring/drift
{
  "node_id": "silo-1",
  "model_name": "alpha",
  "version": "1.0.0",
  "feature": "age",
  "bin_edges": [0, 10, 20, 30, 40, 50],
  "bin_counts": [12, 45, 78, 33, 7],
  "timestamp": "2026-05-14T00:00:00Z"
}
```

### 알림 규칙 (자동 롤백 연동)
```http
POST /api/monitoring/rules
{
  "rule_id": "accuracy-floor",
  "model_name": "alpha",
  "metric": "accuracy",
  "threshold": 0.7,
  "comparison": "lt",
  "auto_rollback": true
}
```

### A·B 테스트 시작
```http
POST /api/ab-tests
{
  "test_id": "alpha-v11-vs-v10",
  "model_name": "alpha",
  "control_version": "1.0.0",
  "treatment_version": "1.1.0",
  "group_id": "production",
  "primary_deployment_id": "deploy-uuid-here",
  "metric": "accuracy",
  "min_samples_per_arm": 50,
  "significance_threshold": 2.0
}
```

### 정제 레시피 + 잡
```http
POST /api/cleaning-recipes
{
  "name": "hospital",
  "version": "1.0.0",
  "steps": [
    {"type": "drop_nulls", "params": {"columns": ["age", "blood_type"]}},
    {"type": "clip_outliers", "params": {"column": "glucose", "lower": 50, "upper": 400}},
    {"type": "dedupe", "params": {"keys": ["patient_id"]}}
  ]
}

POST /api/cleaning-jobs
{
  "job_id": "patients-2026q2",
  "recipe_name": "hospital",
  "recipe_version": "1.0.0",
  "group_id": "production",
  "dataset_label": "patients_2026Q2"
}
```
