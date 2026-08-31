# P0 API 계약 — platform SPA ↔ app/ FastAPI 폴링 매핑

- 날짜: 2026-08-21
- 범위: **읽기 전용 폴링 3종** (P0). 변이(라운드 open, 배포 실행)는 P1~P2에서 별도 계약.
- 활성 조건: 설정에서 **목 데이터 OFF** + 빌드 환경변수 **`VITE_API_BASE`** 설정
  (예: `platform/.env.local`에 `VITE_API_BASE=http://localhost:8000`).
  `FED_API_KEY`를 쓰는 서버면 `VITE_FED_API_KEY`도 설정 — 모든 요청에 `X-FED-API-Key` 헤더.
- 폴링 주기: 5초 (`LIVE_POLL_INTERVAL_MS`). 실패는 로그 탭에 1회 기록(연속 실패 스팸 금지),
  복구 시 재기록.

## 1. 사일로 리소스 → `useSiloStore.silos`

| 요청 | `GET /api/resources/usage` + `GET /api/resources/limits` (병렬) |
|---|---|
| 응답 | `ResourceUsageSummary[]` — `silo_id: str`, `cpu_pct`, `mem_pct`, `gpu_pct?`, `disk_pct?`, `over_budget`, `last_sample_at` |
| 임계값 | `ResourceLimit[]` — `silo_id`, `cpu_pct_max?`, `mem_pct_max?`, `disk_pct_max?` |

매핑 (`Silo` 타입):

| UI 필드 | 서버 값 | 규칙 |
|---|---|---|
| `id: number` | `silo_id: str` | 문자열 끝 숫자 추출 (`silo-3` → 3). 숫자 없으면 목록 순번+1000 |
| `name` | `silo_id` | 그대로 표시 |
| `endpoint` | — | 서버가 제공하지 않음 → `"(실서버)"` 고정 |
| `collectIntervalSec` | — | 제공하지 않음 → `0` |
| `cpu` / `mem` / `disk` | `*_pct` | 반올림, `disk_pct` null → 0 |
| `thresholds` | `limits` 매칭 | `*_pct_max` null → 기본값 85/80/90 |

## 2. 성능 지표 → `useSimulationStore.chartPoints` / `monitorPoints` / `global`

| 요청 | `GET /api/monitoring/metrics?metric=accuracy&limit=500` 외 `latency_ms`, `throughput_rps` 병렬 3회 |
|---|---|
| 응답 | `PaginatedResponse<MetricSample>` — `items[].{node_id, metric, value, timestamp}` |

매핑 규칙:

- **라운드 축이 없다** — `MetricSample`에 round 개념이 없으므로, `timestamp`로 그룹핑해
  시간순 인덱스를 라운드 번호로 쓴다(동일 timestamp = 동일 라운드로 간주, 사일로 값 평균).
- `accuracy`는 서버가 **0~1 스케일** → UI는 % 이므로 **×100**.
- `chartPoints[i] = { round: i, accuracy: avg(acc)*100, loss: 0 }` — 서버에 loss 지표가 없으면 0
  (성능 차트는 loss 축이 0으로 깔림 — P2에서 라운드 집계 결과로 대체 예정).
- `monitorPoints[i] = { round: i, throughput: avg(rps), latency: avg(ms), drift: 0 }` —
  드리프트는 P0 범위 밖(`/api/monitoring/drift`는 push 전용).
- `global.accuracy` = 마지막 chartPoint의 accuracy.

## 3. 라운드 상태 → `useSimulationStore.currentRound`

| 요청 | `GET /api/training-rounds` |
|---|---|
| 응답 | `TrainingRound[]` — `round_id`, `status(open/aggregating/completed/failed)`, `contributors[]`, `total_samples`, … |

- `currentRound` = 배열 길이(개설된 라운드 수). 라운드 번호 개념이 서버에 없어서 개수로 대신한다.
- `status`별 시각화(open→다운로드 애니메이션 등)는 P2 범위.

## 불변 규칙

- 이 계약의 모든 필드는 스칼라·카운트뿐이다. **원시 데이터 필드를 추가하지 않는다.**
- 목 모드(`mockEnabled=true`)에서는 어떤 폴링도 돌지 않는다 — 시뮬레이션과 실데이터 혼합 금지.
- 매핑 함수는 `platform/src/api/mappers.ts`의 순수 함수로 두고 vitest로 고정한다.
