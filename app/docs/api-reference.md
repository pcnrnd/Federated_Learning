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
| POST | `/api/monitoring/drift` | PSI 평가 + 자동 알림/재교육 트리거 |
| POST | `/api/monitoring/rules` | 알림 규칙 upsert |
| GET | `/api/monitoring/rules` | 규칙 목록 |
| DELETE | `/api/monitoring/rules/{id}` | 규칙 제거 |
| GET | `/api/monitoring/alerts` | 알림 인스턴스 |
| POST | `/api/monitoring/alerts/{id}/ack` | ACK |
| GET | `/api/monitoring/audit` | 감사 로그 tail |
| GET | `/api/monitoring/retrain-triggers` | 재교육 트리거 조회 |
| GET | `/api/monitoring/prometheus` | Prometheus exposition |

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
| POST | `/api/cleaning-jobs/{id}/shards/{shard_index}/report` | 샤드 결과 보고 |

## 시각화 (P2)

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/visualizations` | 5종 차트 카탈로그 |
| GET | `/api/visualizations/timeseries` | 메트릭 시계열 |
| GET | `/api/visualizations/histogram` | 분포 히스토그램 |
| GET | `/api/visualizations/silo-bar/resource` | 사일로별 리소스 |
| GET | `/api/visualizations/silo-bar/round` | 라운드 기여 |
| GET | `/api/visualizations/heatmap` | 사일로 × 메트릭 격자 |
| GET | `/api/visualizations/topology` | 그룹/배포 토폴로지 |

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
