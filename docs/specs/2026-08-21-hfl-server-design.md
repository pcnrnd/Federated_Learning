# HFL(계층형 연합학습) 서버 이식 설계 — P4

> **범위 주의 — 백엔드 PoC 기록물.**
> 본 문서의 대상은 `backup/poc2/`(구 `app/`) FastAPI 백엔드다. 저장소 재편으로
> 해당 백엔드는 `backup/` 아래 아카이브로 이동했고, 현재 라이브 앱은 자체 백엔드 없이
> 동작하는 React 시뮬레이션 SPA `platform/`(선택적 읽기 전용 폴링만 지원)이다.
> **따라서 본 문서는 `platform/`의 기준·요구 문서가 아니다.** `platform/`의 기준 문서는
> [2026-07-24-silo-hierarchy-design.md](./2026-07-24-silo-hierarchy-design.md)다.
> 본문에서 `app/`으로 표기된 경로는 모두 현재 `backup/poc2/`로 읽는다.
>
> 집계 모델 차이 1건도 함께 기록한다: 본 문서는 집계자 제출의 `sample_count`를
> "하위 합계"로 서술하지만(§3·§4.2·§4.3), `platform/`은 **상위 자신 + 하위**를 엣지
> 집계에 포함한다(`platform/src/lib/aggregation.ts` `aggregateHierarchy`). 사일로는
> 조직 경계이자 데이터 보유자이므로 `platform/` 쪽이 기준이며, 서버 작업 재개 시
> 문구를 "자신 + 하위 합계"로, provenance를 `{silo_id} ∪ aggregated_from`으로 정정한다.
> (구현된 검증 로직 자체는 양쪽을 모두 허용한다 —
> `backup/poc2/services/silo_group_service.py` `_validate_topology` ⑤ "집계자는 루트
> 그룹 멤버여야 정상")

- 날짜: 2026-08-21
- 상태: **구현 완료** — 이후 대상 백엔드가 `backup/poc2/`로 아카이브되어 신규 작업 대상 아님
- 선행: [2026-07-24-silo-hierarchy-design.md](./2026-07-24-silo-hierarchy-design.md) (UI 구현 완료),
  [2026-08-21-p0-api-contract.md](./2026-08-21-p0-api-contract.md) (P0 폴링 연동 완료)
- 대상: `app/` FastAPI (현 `backup/poc2/`) — `platform/` 시뮬레이션에만 있는 HFL 2단 집계를
  실제 백엔드로 이식

## 1. 배경과 목표

UI는 `사일로(로컬 집계자) → 하위 노드` 계층과 6페이즈 HFL 라운드를 구현했지만
(`platform/src/lib/aggregation.ts`), 서버(`fedavg_aggregator.aggregate`)는 평면 집계만 안다.
목표: 서버가 **계층을 등록·검증·기록**하고, 엣지 집계 기여를 받아 글로벌 집계까지
정확히 수행하며, **하위 노드 0개면 기존 평면 동작과 바이트 단위로 동일**할 것.

## 2. 핵심 설계 원리 — FedAvg 결합법칙

가중평균은 결합법칙이 성립한다:

```
글로벌 = Σ(n_k/N)·θ_k  =  Σ(N_c/N)·[Σ(n_k/N_c)·θ_k]   (N_c = 클러스터 c의 샘플 합)
        평면 집계              엣지 집계 후 글로벌 집계
```

따라서 **엣지 집계자가 하위 파라미터를 로컬에서 가중평균하고, 샘플수 합계와 함께
기여 1건으로 제출하면 중앙의 집계 수학은 변경이 필요 없다.** 이 성질이 이 설계의
기둥이고, 구현 전 property 테스트로 고정한다(§6).

**따라서 서버 변경의 본질은 집계 수학이 아니라 ① 계층 메타데이터, ② 기여 출처
(provenance) 기록·검증, ③ 참여 스냅샷 규칙이다.**

## 3. 결정 사항 (Q&A)

| 질문 | 결정 | 근거 |
|------|------|------|
| 2단 집계를 어디서 수행? | **사일로 측(엣지)** — 집계자가 하위 것을 로컬 평균 후 1건 제출. 중앙이 하위 기여를 직접 받아 2단 계산하는 안(중앙 집계형)은 기각 | §2 결합법칙으로 중앙 무변경. WAN 절감이라는 HFL 본래 성격과 일치. 하위 파라미터가 중앙에 도달하지 않아 프라이버시 경계도 강화 |
| 계층을 어느 도메인에? | **`SiloGroup` 확장** — `aggregator_node_id` 필드 추가. 엣지 클러스터 = "집계자 1 + 하위 멤버들"인 그룹 | 신규 도메인 없이 기존 그룹·멤버십 검증 재사용. UI `parentId` ↔ 클러스터 그룹 1:1 대응 |
| 라운드는 무엇을 대상으로? | 기존대로 **루트 그룹**(1단 사일로들). 엣지 클러스터 그룹은 라운드 대상이 아니라 집계자의 제출 검증용 | 라운드 라이프사이클(`open→aggregating→completed`) 무변경 |
| 기여 출처 기록? | `ParameterContribution`에 **`aggregated_from: list[str]` (선택)** 추가 — 집계자가 대리 제출한 하위 노드 목록. 서버는 해당 클러스터 그룹 멤버십과 대조 검증 | 원시 데이터 아님(id 목록 = 카운트성 메타데이터, 프라이버시 불변식 유지). 리니지·감사에 필요 |
| pending 규칙(라운드 중 등록 노드)? | **라운드 open 시점에 멤버십 스냅샷** — `TrainingRound.member_snapshot: list[str]` 추가, 기여 검증을 현재 그룹이 아닌 스냅샷과 대조 | UI의 pending 플래그와 동일 효과를 서버 원리로: 라운드 도중 그룹 변경이 진행 중 라운드에 영향 불가 |
| 집계자 미제출/비활성? | 그 클러스터 전체가 해당 라운드 미참여 — 별도 처리 없음(`min_contributions` 미달 시 기존 400) | UI 규칙("상위 비활성 → 하위 제외")과 일치. 부분 구제는 YAGNI |
| 계층 깊이? | **2단 제한 유지** — 클러스터 그룹의 멤버는 집계자가 될 수 없음(서버 검증) | UI 설계와 동일. 재귀 계층은 스코프 밖 |

## 4. 상세 설계

### 4.1 스키마 (`models/federated_schemas.py`)

```python
class SiloGroup(BaseModel):
    ...
    # None = 일반(루트) 그룹, 값 있음 = 엣지 클러스터 (해당 노드가 로컬 집계자)
    aggregator_node_id: str | None = None

class ParameterContribution(BaseModel):
    ...
    # 집계자가 대리 제출 시: 로컬 평균에 포함된 하위 노드 id 목록 (평면 제출이면 생략)
    aggregated_from: list[str] = Field(default_factory=list)

class TrainingRound(BaseModel):
    ...
    # open 시점 그룹 멤버 스냅샷 — 라운드 중 그룹 변경 무효화 (pending 규칙).
    # None = 스냅샷 도입 이전 레코드 → 현재 그룹 멤버십으로 폴백 (하위 호환).
    # []   = 멤버 0명 그룹의 진짜 빈 스냅샷 → 기여 전부 403 (폴백하지 않음).
    member_snapshot: list[str] | None = None
```

`ParameterContributionRecord`에도 `aggregated_from` 전파(조회·리니지용).
**원시 데이터 필드는 어디에도 추가하지 않는다.**

### 4.2 서비스

`silo_group_service`:
- 생성/수정 검증 추가: `aggregator_node_id`는 `member_node_ids`에 포함 불가(집계자는
  클러스터의 상위), 다른 클러스터의 멤버가 집계자가 될 수 없음(2단 제한),
  한 노드는 최대 1개 클러스터의 멤버(중복 소속 금지).
- `get_cluster_by_aggregator(node_id)` 헬퍼 — 기여 검증에서 사용.

`training_round_service`:
- `create_round`: 루트 그룹 멤버를 `member_snapshot`으로 동결.
- `_verify_membership`: 현재 그룹 대신 **스냅샷과 대조**로 변경.
- `submit_contribution`: `aggregated_from`이 있으면
  ① 제출자가 그 클러스터의 `aggregator_node_id`인지,
  ② 목록이 클러스터 멤버의 부분집합인지 검증 (아니면 403/422).
  수학은 무변경 — `sample_count`가 이미 하위 합계이므로 기존 `aggregate()` 그대로.

`fedavg_aggregator`: **무변경.** (결합법칙 검증 테스트만 추가)

### 4.3 silo_sdk (`app/silo_sdk/`)

`edge.py` 신규 — stdlib만 사용(기존 SDK 규약):

```python
def combine(children: list[tuple[str, int, list[float]]]) -> tuple[int, list[float]]:
    """하위 (silo_id, sample_count, params) → (샘플 합, 가중평균 파라미터).
    fedavg_aggregator.aggregate와 동일 수식 — 차원 불일치/비양수 샘플수 거부."""
```

집계자 사용 흐름: 하위들로부터 파라미터 수집(사내망, SDK 범위 밖) →
`combine()` → `client.push_parameters(..., sample_count=합계, aggregated_from=[...])`.
`push_parameters` 시그니처에 `aggregated_from` 선택 인자 추가(기본 빈 목록 — 기존 호출 무변경).

### 4.4 API

신규 엔드포인트 없음. 기존 `/api/silo-groups` CRUD·`/api/training-rounds`가
새 필드를 그대로 나른다. UI(P2 배선 시)는 클러스터 그룹 생성으로 하위 노드 증설을 표현.

## 5. 엣지 케이스

| 케이스 | 동작 |
|--------|------|
| `aggregated_from` 빈 목록(평면 제출) | 기존 경로와 완전 동일 — 검증·수학 모두 무변경 |
| 집계자가 자기 자신을 `aggregated_from`에 포함 | 422 (하위 목록엔 하위만) |
| 스냅샷에 없는 노드의 기여 | 403 (라운드 중 등록 노드 → 다음 라운드부터) |
| 클러스터 멤버가 중앙에 직접 기여 | 403 — 클러스터 멤버는 루트 그룹 소속이 아니므로 스냅샷 검증에서 자동 차단 |
| 집계자 미제출 | 클러스터 전체 미참여, `min_contributions` 미달 시 기존 400 |
| 라운드 중 클러스터 멤버 변경 | 진행 중 라운드는 스냅샷 기준이라 무영향, 다음 라운드부터 반영 |

## 6. 테스트 계획 (pytest, 구현 전 작성)

- `test_fedavg.py` 확장 — **결합법칙 property**: 무작위 파라미터/샘플수로
  `평면 aggregate == combine 후 aggregate` (수치 오차 ≤1e-9), 하위 0개 동일성.
- `test_silo_groups.py` 확장 — 집계자 검증 3종(멤버 겸직 금지·2단 제한·중복 소속 금지).
- `test_training_round.py` 확장 — 스냅샷 동결, `aggregated_from` 검증(403/422 경로),
  집계자 대리 제출 end-to-end(제출→집계→AggregateResult 값 검증, 손계산 기대값 대조).
- `test_silo_sdk.py` 확장 — `combine()` 가중평균·차원 검증, `push_parameters` 하위 목록 전달.
- 게이트: `pytest --cov-fail-under=80` + `ruff check` + `ruff format --check` (기존 CI).

## 7. 변경 파일 목록

| 파일 | 변경 |
|------|------|
| `models/federated_schemas.py` | `aggregator_node_id`, `aggregated_from`, `member_snapshot` |
| `services/silo_group_service.py` | 클러스터 검증 3종 + `get_cluster_by_aggregator` |
| `services/training_round_service.py` | 스냅샷 동결·검증, 대리 제출 검증 |
| `services/fedavg_aggregator.py` | 무변경 (테스트만 추가) |
| `silo_sdk/edge.py` (신규) | `combine()` |
| `silo_sdk/client.py` / `async_client.py` | `push_parameters(aggregated_from=...)` |
| `tests/test_fedavg.py` 외 3파일 | §6 테스트 |

스토리지 마이그레이션 불필요 — 신규 필드 전부 기본값 있는 선택 필드라 기존
YAML/SQLite 레코드와 하위 호환.

## 8. 스코프 밖 (명시적 제외)

- 하위 노드의 실제 학습 런타임·사내망 수집 프로토콜 (실험 환경 2단계에서)
- 3단 이상 재귀 계층, 엣지 장애 부분 구제, Secure Aggregation의 계층 적용
- UI 배선 (P2에서 클러스터 그룹 CRUD 연결)

## 9. 검증 이력

1. 사용자 검토·승인 완료 → 테스트 선행(§6) → 구현.
2. 독립 리뷰(신규 세션, 재현 스크립트 작성)에서 **HIGH 2건 검출·정정** —
   ① 2단 제한이 그룹 생성 순서에 따라 우회되어 3단 체인 성립,
   ② 클러스터 멤버가 루트 그룹에 중복 소속되면 **표본 이중 계상**(오류 없이 글로벌 모델 오염).
   두 건 모두 검증을 한 지점(`_validate_topology`)으로 모아 양방향 검사로 정정하고,
   원본 재현 스크립트 재실행으로 차단을 확인했다.
3. pytest **183 → 227케이스 전 통과**. 신규 필드 전부 기본값이라 스토리지 마이그레이션 없음.
4. 이후 저장소 재편으로 대상 백엔드가 `backup/poc2/`로 이동 — 구현 산출물은
   `backup/poc2/{models/federated_schemas.py, services/silo_group_service.py,
   services/training_round_service.py, silo_sdk/edge.py}`에 있다.
