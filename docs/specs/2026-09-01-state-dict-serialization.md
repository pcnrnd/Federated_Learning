# state_dict ↔ 평탄 벡터(list[float]) 직렬화 규약

- 날짜: 2026-09-01
- 범위: 사일로 로컬 학습 결과(`ParameterContribution.parameters`)와 글로벌 집계 결과
  (`AggregateResult.parameters`)가 공유하는 **평탄화된 파라미터 벡터**의 생성·복원 규칙.
- 적용 대상: `platform/backend/silo_sdk/trainer.py`(순수 파이썬 학습기),
  향후 torch 기반 사일로 학습기, `services/fedavg_aggregator.py` 소비자 전부.

## 1. 왜 평탄 벡터인가

전송 스키마(`ParameterContribution`)는 개인정보 보호 불변식에 따라
**스칼라·벡터 외 구조를 금지**한다. 모델 구조(레이어 이름·shape)는 라운드의
`model_name@version`으로 양측이 이미 합의한 상태이므로, 벡터에 메타데이터를
싣지 않아도 복원이 가능하다.

## 2. 평탄화 (state_dict → list[float])

1. **키 순서**: `state_dict`의 **삽입 순서 그대로** (torch는 모델 정의 순서를 보존한다).
   키를 정렬하지 않는다 — 정렬하면 프레임워크 간 순서가 달라진다.
2. **텐서 평탄화**: 각 텐서를 **row-major(C-order)** 로 평탄화한다
   (`tensor.detach().cpu().double().flatten().tolist()`).
3. **이어붙이기**: 키 순서대로 平탄화 결과를 하나의 `list[float]`로 연결한다.
4. **수치 규약**: IEEE 754 float64(JSON number). `NaN`/`Infinity` 금지 —
   발생 시 기여를 제출하지 말고 로컬에서 실패 처리한다.

```python
def flatten_state_dict(sd: dict) -> list[float]:
    out: list[float] = []
    for key in sd:                       # 삽입 순서 유지
        out.extend(float(v) for v in sd[key].flatten().tolist())
    return out
```

## 3. 복원 (list[float] → state_dict)

수신 측은 **동일 아키텍처의 참조 state_dict**(키·shape)를 기준으로 순서대로 슬라이스한다.
총 길이가 `Σ numel(shape)`와 다르면 즉시 오류다 — 집계기(`fedavg_aggregator`)도
차원 불일치 기여를 거부한다.

```python
def unflatten(flat: list[float], ref: dict) -> dict:
    out, i = {}, 0
    for key, shape in ref.items():       # ref: key → shape
        n = math.prod(shape)
        out[key] = reshape(flat[i : i + n], shape)
        i += n
    assert i == len(flat), "파라미터 차원 불일치"
    return out
```

## 4. 선형(릿지) 모델 특례 — trainer.py 규약

`silo_sdk.trainer.train_ridge`는 특징 d개의 선형 모델을 다음 순서로 평탄화한다:

```text
parameters = [w_1, w_2, ..., w_d, b]      # 길이 d+1, 편향(b)이 마지막
```

이는 `torch.nn.Linear(d, 1)`의 `state_dict()`
(`weight: (1, d)` → row-major 평탄화 = `[w_1..w_d]`, 그다음 `bias: (1,)` = `[b]`)를
§2 규칙으로 평탄화한 결과와 **동일**하다. 즉 순수 파이썬 학습기와 torch 학습기가
같은 라운드에 섞여 기여해도 FedAvg 가중평균이 성립한다.

## 5. 검증·무결성

- `parameter_dim`: 서버는 기여 저장 시 벡터 길이를 기록하고, 집계 시 차원 불일치를 400으로 거부.
- `checksum`(선택): 벡터의 정규 JSON 직렬화(`json.dumps(params, separators=(",", ":"))`)에
  대한 SHA-256 hex. 전송 무결성 확인용이며 서버는 값 존재 시 그대로 보존한다.
- 원시 데이터 금지: 벡터에는 **학습된 파라미터만** 담는다. 개별 표본·통계량을 섞지 않는다.
