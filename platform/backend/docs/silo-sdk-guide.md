# 사일로 SDK 가이드

> 사일로 측에서 사용하는 `app/silo_sdk` 패키지의 사용 매뉴얼.
> 외부 의존성 없이 stdlib(urllib + asyncio)만 사용 — 사일로 환경에 부담 없이 설치 가능.

## 설치

`app/silo_sdk/` 디렉토리 전체를 사일로 측에 복사하거나, 본 저장소를 path로 추가.

```python
import sys
sys.path.insert(0, "/path/to/Federated_Learning/app")
from silo_sdk import SiloClient, AsyncSiloClient, apply_recipe, build_histogram
```

## 동기 클라이언트 (`SiloClient`)

### 기본 사용
```python
from silo_sdk import SiloClient

client = SiloClient(
    base_url="http://central:8000",
    silo_id="silo-2",        # 중앙의 servers.yaml에 등록된 노드 ID와 일치
    timeout=10.0,
    retries=3,                # 5xx + 네트워크 오류 시 지수 백오프 재시도
)
```

### 메트릭 push
```python
client.push_metric("alpha", "1.0.0", "accuracy", 0.93)
client.push_metric("alpha", "1.0.0", "latency_ms", 42.7)
client.push_metric("alpha", "1.0.0", "throughput_rps", 318.0)
```

### 분포 통계 push (개인정보 보호)
```python
from silo_sdk import build_histogram

# 로컬 데이터에서 히스토그램만 추출 (원시 값은 외부 유출 ❌)
bin_edges = [0.0, 10.0, 20.0, 30.0, 40.0, 50.0]
bin_counts = build_histogram(local_age_values, bin_edges)

client.push_distribution(
    model_name="alpha",
    version="1.0.0",
    feature="age",
    bin_edges=bin_edges,
    bin_counts=bin_counts,
)
```

### 학습 파라미터 기여 (FedAvg)
```python
# 사일로가 로컬 학습 후 도출한 파라미터 벡터
local_params = [...]   # list[float]
client.push_parameters(
    round_id="abc123",
    sample_count=len(local_dataset),
    parameters=local_params,
)
```

### 리소스 모니터링
```python
import psutil  # 사일로 측에서만 사용

client.push_resource_sample(
    cpu_pct=psutil.cpu_percent(),
    mem_pct=psutil.virtual_memory().percent,
    gpu_pct=None,                 # 옵셔널
    disk_pct=psutil.disk_usage("/").percent,
)
```

### 데이터 정제
```python
from silo_sdk import apply_recipe

# 1. 중앙에서 레시피 조회
recipe = client.fetch_cleaning_recipe("hospital", "1.0.0")

# 2. 샤드 처리 시작 알림
client.start_cleaning_shard(job_id="patients-2026q2", shard_index=0)

# 3. 로컬 데이터에 레시피 적용 (cleaned_rows는 사일로에 유지)
local_rows = [...]   # list[dict]
cleaned_rows, counters = apply_recipe(local_rows, recipe["steps"])

# 4. 통계만 보고 (원시 데이터 ❌)
client.report_cleaning_shard(
    job_id="patients-2026q2",
    shard_index=0,
    rows_in=len(local_rows),
    rows_out=len(cleaned_rows),
    step_counters=counters,
)
```

### 다원천 통합 정제 (수평·수직·교차)

레시피에 매핑표(`mapping`)가 있으면 `apply_recipe`가 원천 묶음 `{원천 이름: 행 목록}`을 받는다.
수평(기간별 표 행 결합) → 수직(키 결합) → 교차(다른 단위·코드의 기록 변환과 충돌 해소) →
정합성 검사 순으로 공통 스키마를 만든다. 카운터에는 단계별 세부(`<step>.<항목>`)가 함께 담긴다.

```python
from silo_sdk.integration import load_sources

tables = load_sources({"period_a": "period_a.csv", "entity": "entity.csv", ...})
cleaned, counters = apply_recipe(tables, recipe["steps"], mapping=recipe["mapping"])
# counters 예: validate_schema.excluded.missing, union_sources.duplicates.cross,
#              join_sources.excluded.left_only, map_schema.cast_failed
```

### 사일로 간 수직 정렬 (HMAC 교집합)

같은 엔터티를 서로 다른 사일로가 가질 때, 원본 id를 보내지 않고 공통 엔터티만 같은 순서로 맞춘다.

```python
from silo_sdk.alignment import align_rows, hash_ids, load_align_key

key = load_align_key()                       # 사일로 환경변수 FED_ALIGN_KEY (16자 이상)
digests = hash_ids((r["id"] for r in cleaned), key)   # {HMAC-SHA256 hex: id}
client.submit_alignment_keys("a1", list(digests))     # 다이제스트만 전송
intersection = client.get_alignment_intersection("a1")["hashed_keys"]  # 모두 제출 전 409
aligned, report = align_rows(cleaned, "id", intersection, key)  # 교집합만, 서버 순서대로
client.report_alignment("a1", report["matched"], report["excluded"], report["order_digest"])
```

한계(이번 구현의 보안 수준):

- 키를 사일로끼리 공유한다. 키를 가진 사일로는 다른 사일로의 다이제스트를 추측 가능한 id
  사전(예: 순번 id)과 대조해 상대의 엔터티 보유 여부를 알 수 있다.
- 서버는 키가 없어 다이제스트를 id로 되돌리지 못하지만, 교집합 크기와 어떤 다이제스트가
  공통인지는 안다. 키가 서버로 새면 같은 사전 대조가 가능하다 — 키는 서버 환경에 두지 않는다.
- 강화하려면 키 공유 없는 PSI(사설 교집합: ECDH·OPRF 기반)로 바꿔야 한다. 수직 연합학습
  알고리즘(정렬된 엔터티로 특징을 나눠 학습)은 이번 범위 밖이다.

### 오류 처리
```python
from silo_sdk import SiloClient, SiloClientError

try:
    client.push_metric("alpha", "1.0.0", "accuracy", 0.93)
except SiloClientError as exc:
    if exc.status == 404:
        # 모델/노드 미등록 — 중앙 운영자에게 보고
        ...
    elif exc.status >= 500:
        # 재시도는 SDK가 이미 retries회 수행한 뒤 — 일시적 장애로 판단
        ...
```

## 비동기 클라이언트 (`AsyncSiloClient`)

다수 push를 동시 처리할 때 유리. 내부적으로 sync SiloClient를 `asyncio.to_thread`로 래핑.

```python
import asyncio
from silo_sdk import AsyncSiloClient

async def main():
    client = AsyncSiloClient("http://central:8000", silo_id="silo-2")

    # 단일 push
    await client.push_metric("alpha", "1.0.0", "accuracy", 0.93)

    # 다중 메트릭 동시 push (wall-clock 단축)
    samples = [
        ("alpha", "1.0.0", "accuracy", 0.93),
        ("alpha", "1.0.0", "latency_ms", 42.0),
        ("alpha", "1.0.0", "throughput_rps", 318.0),
    ]
    results = await client.push_many_metrics(samples)

asyncio.run(main())
```

## 정제 step 카탈로그

`apply_recipe`가 지원하는 8종 step:

| step type | 필수 파라미터 | 동작 |
|---|---|---|
| `drop_nulls` | `columns` | 지정 컬럼 중 null/빈문자열인 행 제거 |
| `clip_outliers` | `column`, `lower`, `upper` | 범위 밖 값을 양 끝으로 클리핑 |
| `dedupe` | `keys` | 키 조합 중복 제거 |
| `cast` | `column`, `to` | `int/float/str/bool` 변환 |
| `normalize` | `column` | z-score 또는 min-max (`params.method`) |
| `trim_whitespace` | `columns` | 문자열 양끝 공백 제거 |
| `lowercase` | `columns` | 문자열 소문자화 |
| `regex_filter` | `column`, `pattern` | 정규식 매칭되지 않는 행 제거 |

다원천 단계(레시피 `mapping` 필요 — 서버 `STEP_CATALOG`와 SDK `SUPPORTED_STEPS`는 테스트로 일치를 고정):

| step type | 필수 파라미터 | 동작 |
|---|---|---|
| `map_schema` | `sources` | 표 원천을 공통 스키마로 (컬럼명·코드표·형 변환·단위 배율/오프셋), 실패 값은 결측으로 두고 사유별 집계 |
| `validate_schema` | (`source` 선택) | 존재·형식·유한·범위 위반 행 제외, 사유별 집계. 유효 행 0이면 정제 실패 |
| `union_sources` | `sources`, `into` | 수평 결합 — 행 결합 + 원천 간·안 중복 제거 |
| `join_sources` | `left`, `right`, `into` | 수직 결합 — 키 inner join, 제외 수 기록 |

## 원시 데이터 절대 금지

SDK 자체가 다음 필드를 노출하지 않는다:
- 푸시 메서드는 `row`/`raw`/`sample` 등 데이터 페이로드 필드를 받지 않는다.
- `apply_recipe`의 cleaned_rows는 **리턴값으로만** 노출되며 자동으로 push되지 않는다.
- 호출자가 명시적으로 통계/카운터를 `report_cleaning_shard`에 전달할 때만 외부로 나간다.

## 풀 예시: FL 라운드 1주기
```python
from silo_sdk import SiloClient

client = SiloClient("http://central:8000", silo_id="silo-2")

# 1. 현재 라운드 정보 조회
rnd = client.get_round("round-id-here")
# rnd["status"] == "open" 확인

# 2. 로컬 학습 (사일로 측 코드)
local_params, sample_count = train_locally(rnd["model_name"], rnd["version"])

# 3. 파라미터 push
client.push_parameters(
    round_id=rnd["round_id"],
    sample_count=sample_count,
    parameters=local_params,
)

# 4. 메트릭 보고
client.push_metric(rnd["model_name"], rnd["version"], "accuracy", local_acc)

# 5. 리소스 + 분포 통계도 동시에
client.push_resource_sample(cpu_pct=70.0, mem_pct=55.0)
client.push_distribution(
    rnd["model_name"], rnd["version"],
    feature="age",
    bin_edges=[...], bin_counts=[...]
)
```
