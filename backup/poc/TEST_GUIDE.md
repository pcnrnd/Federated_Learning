# [TEST_GUIDE.md] 분산형 데이터 연합컴퓨팅 플랫폼 테스트 및 검증 가이드
(PoC Verification & Test Instruction)

본 문서는 **연합컴퓨팅 플랫폼 PoC** 환경의 정상 작동 상태 및 핵심 알고리즘(신원 은닉 ID 조인, FedAvg 등)의 기능 무결성을 검증하기 위한 테스트 가이드입니다.

---

## 1. 테스트 범위 및 프레임워크 개요

플랫폼의 검증은 다음 3가지 영역에서 독립적으로 또는 통합하여 수행됩니다.

```
[1단계] 사일로 및 인프라 검증 (Smoketest / Docker-H)
   └── [2단계] API 및 비동기 스케줄러 검증 (Pytest / FastAPI TestClient)
         └── [3단계] 신원 은닉 ID 조인 알고리즘 검증 (test/test.py)
```

---

## 2. 1단계: 격리 인프라 스모크 테스트 (Infrastructure Smoketest)

원격 사일로와 도커 호스트 환경의 네트워크 바인딩 상태를 검증합니다.

### 2.1 원격 사일로 Docker TCP 응답 확인
호스트 터미널에서 각 사일로의 독립 Docker 데몬 API에 버전 질의를 보내 정상 응답이 오는지 확인합니다.
```bash
# 사일로 1 연결 상태 조회 (기대 결과: Docker 데몬 메타데이터 상세 출력)
docker -H tcp://localhost:2371 version

# 사일로 2 연결 상태 조회
docker -H tcp://localhost:2372 version

# 사일로 3 연결 상태 조회
docker -H tcp://localhost:2373 version
```

### 2.2 MinIO 오브젝트 스토리지 연결성 테스트
curl 명령어를 사용하여 각 사일로의 MinIO 가용 서버 헬스체크를 수행합니다.
```bash
curl -I http://localhost:7001/minio/health/live
# 기대 응답: HTTP/1.1 200 OK
```

---

## 3. 2단계: API 및 스케줄러 단위 테스트 (Pytest Unit Tests)

FastAPI 엔진의 주요 엔드포인트 기능과 스케줄러의 비동기 라이프사이클을 `pytest`로 검증합니다.

```bash
# app 디렉토리로 이동 (통합 플랫폼 소스 위치)
cd app

# pytest 의존 패키지 설치
pip install -r requirements-dev.txt

# 전체 단위 테스트 세트 일괄 실행
pytest
```

* **주요 테스트 커버리지**:
  * `tests/test_main.py`: `/readyz` 헬스체크 및 API 키 미들웨어 정상 인증 차단율 검증.
  * `tests/test_nodes.py`: `servers.yaml` 데이터 가입 및 `type`/`role` 자동 제어 유효성 테스트.
  * `tests/test_scheduler.py`: APScheduler의 스레드 충돌 방지 및 라운드 예약 큐 적재 정확성 테스트.

---

## 4. 3단계: 신원 은닉 ID 조인 알고리즘 실증 (`test/test.py` 실행)

각 사일로 간의 민감한 원식 데이터셋(예: 환자 명단 등)을 교환하지 않고, 개인식별정보(PII) 누출 없이 교집합(Intersection) 데이터를 정렬·조인하는 **PSI(Private Set Intersection) 연산 엔진**을 독립 실행하여 동작을 증명합니다.

```bash
# test 디렉토리로 이동
cd ../test

# 독립 테스트 스크립트 실행
python test.py
```

### 4.1 핵심 검증 프로세스 및 출력 기대값
스크립트 가동 시 화면 콘솔에 다음과 같은 3단계 연산 흐름이 표시되는지 검증합니다.

1. **ID Normalization (1단계)**: 원시 ID의 공백 제거 및 소문자 정제 후 SHA-256 단방향 암호 해싱 수행.
2. **Intersection 탐색 (2단계)**: 사일로 A와 B의 해시셋 교집합 탐색 성공 메시지.
3. **폴백 기전 동작 검증 (3단계)**: 
   * **환경 A (Pandas 탑재)**: Pandas 고속 Inner-Join 연산 구동 및 가용 밀리초(ms) 단위 성능 표출.
   * **환경 B (Stdlib 전용)**: Pandas 라이브러리 부재 시 순수 Python `dict` 및 `set`을 사용하여 동등한 데이터 정합성 결과 도출 및 유연성(Fault-tolerance) 증명.

---

## 5. 최종 PoC 성공 여부 체크리스트 (Verification Checklist)

연합컴퓨팅 최종 검증 시 아래 체크리스트의 모든 항목이 `PASS` 상태가 됨으로써 PoC가 공식 완수됩니다.

| 검증 영역 | 개별 체크 항목 | 확인 절차 | 결과 (Pass/Fail) |
| :--- | :--- | :--- | :---: |
| **인프라** | 3대 격리 사일로의 데이터 스토리지 완벽 물리 격리 여부 | MinIO 개별 웹 콘솔 접속 및 버킷 데이터 적재 확인 | [ ] PASS |
| **인프라** | `fed-net` 외부 가상망을 통한 컨테이너 제어 가용성 | FCP 대시보드 상에서 사일로 컨테이너 Start/Stop 테스트 | [ ] PASS |
| **보안** | `FED_API_KEY` 탑재 시 외부 무단 접근 전면 거부 여부 | API Key 누락 호출 시 `401 Unauthorized` 수합 검증 | [ ] PASS |
| **알고리즘**| FedAvg 갱신에 따른 연합 모델 가중치 정상 산출 | 라운드 종료 후 취합된 글로벌 파라미터 갱신의 정밀도 검증 | [ ] PASS |
| **알고리즘**| 신원 은닉 조인 시 원시 개인정보 누출 제로화 달성 | `test.py` 구동 후 원시 ID 노출 없이 암호 해시 조인 성공 | [ ] PASS |
| **UI/UX** | 비동기 메트릭 데이터 수집 시 대시보드 블로킹 발생 여부 | 대시보드 갱신 주기별 화면 끊김 현상(CLS) 발생 여부 관측 | [ ] PASS |
