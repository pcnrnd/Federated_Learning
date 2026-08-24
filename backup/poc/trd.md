# [TRD] 분산형 데이터 연합컴퓨팅 플랫폼 기술 요구사항 정의서
(Technical Requirement Document)

| 프로젝트명 | 데이터 활용 강화를 위한 분산형 데이터 연합컴퓨팅 기술 개발 및 실증 (PoC) |
| --- | --- |
| 문서 버전 | v1.0 |
| 작성일자 | 2026-05-27 |
| 작성자 | RND 연구개발팀 (Antigravity AI) |
| 대상 범위 | 3차년도 연구과제 통합 연합컴퓨팅 플랫폼 기술 구조 및 명세 |

---

## 1. 시스템 아키텍처 개요 (System Architecture)

본 플랫폼은 **중앙 FCP 제어 대시보드 (Centralized Orchestrator)** 와 다수의 **격리식 연합컴퓨팅 노드 (Silo Sandbox)** 간의 느슨한 결합(Loose Coupling)을 지향하며, 안전하고 격리된 외부 네트워크 환경(`fed-net`)을 통해 소통합니다.

### 1.1 하이레벨 시스템 아키텍처 다이어그램

```mermaid
graph TB
    subgraph Host_Network ["호스트 네트워크"]
        Dashboard_UI["통합 대시보드 UI (React / HTML5)"]
        FCP_Backend["FCP 통합 백엔드 (FastAPI)"]
        Dashboard_UI <-->|HTTP / REST API| FCP_Backend
    end

    subgraph Fed_Net_External ["외부 보안 네트워크 (fed-net)"]
        FCP_Backend <-->|Docker API (TCP)| Silo_1
        FCP_Backend <-->|Docker API (TCP)| Silo_2
        FCP_Backend <-->|Docker API (TCP)| Silo_3
    end

    subgraph Silo_1 ["사일로 1 Sandbox (DinD)"]
        Inner_Dockerd_1["내부 Docker 데몬 (unix:///var/run/docker.sock)"]
        MinIO_1[("내장 MinIO (Object Storage)")]
        Local_ML_1["로컬 학습/정제 컨테이너"]
        
        Inner_Dockerd_1 <--> Local_ML_1
        Local_ML_1 <-->|S3 API| MinIO_1
    end

    subgraph Silo_2 ["사일로 2 Sandbox (DinD)"]
        Inner_Dockerd_2["내부 Docker 데몬"]
        MinIO_2[("내장 MinIO")]
        Local_ML_2["로컬 학습/정제 컨테이너"]
        
        Inner_Dockerd_2 <--> Local_ML_2
        Local_ML_2 <-->|S3 API| MinIO_2
    end
    
    classDef border fill:#f9f,stroke:#333,stroke-width:2px;
    class Silo_1,Silo_2 border;
```

---

## 2. 세부 기술 스택 (Technology Stack)

| 구분 | 적용 기술 / 라이브러리 | 상세 용도 및 특징 |
| --- | --- | --- |
| **Backend Core** | Python 3.10+ / FastAPI | - 비동기 I/O 기반 고성능 API 처리 및 멀티 노드 모니터링<br>- lifespan 컨텍스트 매니저를 통한 비동기 스케줄러 관리 |
| **Scheduler** | APScheduler (Advanced Python Scheduler) | - 비동기 배치 스케줄링 (`AsyncIOScheduler`) 탑재<br>- 정제 잡 및 연합학습 라운드의 정기적/주기적 실행 자동화 |
| **Silo Sandbox** | Ubuntu 22.04 LTS / Docker-in-Docker | - `privileged: true` 권한으로 독립된 로컬 Docker 데몬 구동<br>- 외부 호스트 환경과 사일로 내부 학습용 컨테이너 간의 완벽한 격리 |
| **Storage** | MinIO Object Storage | - 각 사일로 내부 보안 구역 내 개별 가상 스토리지 구축<br>- 표준 S3 호환 API를 사용한 로컬 학습 데이터셋 격리 저장 |
| **Docker SDK** | `docker` Python SDK | - 중앙 대시보드에서 각 원격/로컬 노드 및 사일로 내부 컨테이너 라이프사이클을 통제하고 자원을 모니터링 |
| **Security** | API Key Middleware (FastAPI) | - `FED_API_KEY` 기반 `X-FED-API-Key` 헤더를 검증하는 Zero-Trust API 게이트웨이 보안 적용 |
| **Frontend** | React SPA / Vanilla JS | - Harmony HSL 컬러 팔레트가 적용된 미려하고 반응성이 뛰어난 5종 차트 및 대시보드 시각화 |

---

## 3. 네트워크 및 인프라 구조 (Network & Port Bindings)

사일로들은 호스트의 포트를 개별 매핑하여 외부에서 관리할 수 있도록 설계되었습니다. 포트 관리 규칙은 아래와 같습니다.

### 3.1 호스트 바인딩 포트 매핑 테이블

| 사일로 ID | 호스트 SSH 포트 | 내부 Docker API 포트 (TCP) | MinIO API 포트 | MinIO Console 웹 UI 포트 | 호스트 데이터 바인딩 경로 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **silo-1** | `2223` | `2371` | `7001` | `7002` | `./data/silo1:/var/lib/docker` |
| **silo-2** | `2224` | `2372` | `7003` | `7004` | `./data/silo2:/var/lib/docker` |
| **silo-3** | `2225` | `2373` | `7005` | `7006` | `./data/silo3:/var/lib/docker` |
| **silo-4~6** | `2226~2228` | `2374~2376` | `7007~7011` | `7008~7012` | 확장 영역 (Compose 주석 처리 및 동적 생성 지원) |

### 3.2 네트워크 세그먼트 격리
* **`fed-net` 외부 네트워크**: `bridge` 모드의 외부 가상 네트워크로, 중앙 대시보드 컨테이너와 사일로 컨테이너 간의 연결 전용 회선 역할을 수행합니다.
* **로컬 사일로 통신**: 각 사일로 내부에서 구동되는 로컬 AI 학습 컨테이너와 MinIO 스토리지 간의 데이터 전송은 사일로 **내부 브릿지망**으로 한정되어 호스트망이나 대시보드망에서 실시간 데이터 패킷을 가로챌 수 없습니다.

---

## 4. 데이터 모델 및 스토리지 스키마

### 4.1 서버 및 노드 설정 스키마 (`servers.yaml`)
중앙 컨트롤러가 관리하는 원격 및 로컬 노드의 메타데이터는 서버 디렉토리 내부 `config/servers.yaml`에 영구 저장됩니다.

```yaml
# 예시 config/servers.yaml
main:
  base_url: "unix://var/run/docker.sock"
  label: "중앙 관리 서버"
  type: "local"
  role: "central"
  tls: false

silo_1:
  base_url: "tcp://localhost:2371"
  label: "의료 연구 사일로 A"
  type: "remote"
  role: "client"
  tls: false

silo_2:
  base_url: "tcp://localhost:2372"
  label: "바이오 연구 사일로 B"
  type: "remote"
  role: "client"
  tls: false
```

### 4.2 Pydantic DTO (Data Transfer Objects)
중앙 API 입출력 검증을 위한 핵심 DTO 스키마 명세입니다.

* **ServerConfig**: 노드 신규 등록 및 수정 시 데이터 유효성 검증
  ```python
  class ServerConfig(BaseModel):
      base_url: str = Field(..., description="Docker API 접속 엔드포인트 URL")
      label: str = Field(..., description="대시보드 표시용 레이블")
      tls: bool = Field(default=False, description="TLS 사용 여부")
  ```
  *(주의: `type`과 `role`은 비즈니스 로직 안전성을 위해 입력으로 받지 않고, `main` ID 여부 등을 판단하여 서버 내부에서 자동 강제 할당함)*

* **ContainerAction**: 원격 사일로 컨테이너 제어 명령 포맷
  ```python
  class ContainerAction(BaseModel):
      action: Literal["start", "stop", "restart"] = Field(..., description="제어 액션")
  ```

---

## 5. 핵심 API 명세 (Interface & RESTful API)

플랫폼 백엔드는 `app/api/` 폴더 내에 마이크로 서비스 형태로 라우터가 분리되어 있습니다.

### 5.1 모델 패키징 & 배포 API (`deployments`, `packaging`)
* **`POST /api/models`**: 신규 가입소 모델 업로드 및 패키징.
* **`POST /api/deployments`**: 특정 모델을 지정한 사일로/노드에 Docker 컨테이너 형식으로 배포.
* **`DELETE /api/deployments/{deployment_id}`**: 배포 모델 컨테이너 기동 중지 및 회수.

### 5.2 사일로 링크 및 연합학습 제어 API (`silo_groups`, `training_rounds`)
* **`POST /api/silo-groups`**: 격리된 사일로 노드들을 그룹화.
* **`POST /api/rounds`**: 신규 연합학습 라운드 트리거.
* **`POST /api/rounds/{round_id}/parameters`**: 사일로가 학습한 로컬 모델 가중치(파라미터)를 S3/MinIO 임시 버킷 혹은 API 페이로드를 통해 백엔드로 업로드.

### 5.3 데이터 정제 API (`cleaning_recipes`, `cleaning_jobs`)
* **`POST /api/cleaning-recipes`**: JSON 기반 데이터 정제 가이드(결측치 보간 규칙, 아웃라이어 제거 스키마 등) 정의.
* **`POST /api/cleaning-jobs`**: 특정 노드의 데이터를 타겟으로 정의된 정제 레시피를 실행하는 배치 잡 트리거.

### 5.4 리소스 & 모델 모니터링 API (`resources`, `monitoring`)
* **`GET /api/resources/{node_id}`**: 실시간 호스트/컨테이너 CPU 및 메모리 가용성 메트릭 반환.
* **`GET /api/monitoring/drift`**: 데이터/모델 드리프트(Jensen-Shannon Divergence 등 통계 지표 기반) 계산 결과 조회.

---

## 6. 핵심 연합컴퓨팅 알고리즘 및 워크플로우

### 6.1 FedAvg (Federated Averaging) 알고리즘 구현 로직

연합학습 가중치 집계는 개별 사일로의 가중치를 샘플 수($n_k$) 비율로 가중 평균하여 글로벌 모델 파라미터($w_{t+1}$)를 갱신합니다.

$$w_{t+1} \leftarrow \sum_{k=1}^{K} \frac{n_k}{N} w_{t+1}^k$$

```python
def aggregate_parameters(local_weights: list[dict], sample_sizes: list[int]) -> dict:
    """FedAvg 알고리즘 기반 파라미터 가중 평균 집계 구현체"""
    total_samples = sum(sample_sizes)
    if total_samples == 0:
        raise ValueError("총 데이터 샘플 수가 0일 수 없습니다.")
        
    global_weights = {}
    # 파라미터 텐서 키별로 순회하며 가중치 누적
    for key in local_weights[0].keys():
        weighted_sum = 0.0
        for i, weights in enumerate(local_weights):
            weight_factor = sample_sizes[i] / total_samples
            weighted_sum += weights[key] * weight_factor
        global_weights[key] = weighted_sum
        
    return global_weights
```

### 6.2 Standalone PSI 및 ID 정제/조인 로직 (`test/test.py` 참조)
사일로 간 데이터 결합 시 발생할 수 있는 신원 은닉(Privacy-Preserving) 조인을 위해 **SHA-256 기반 ID 정제화 및 Set-Intersection(교집합) 처리 논리** 가 구현되어 있습니다.

1. **ID 정제(Normalization)**: 공백 제거, 소문자화, 특수문자 제거 후 SHA-256 단방향 암호화 수행.
2. **PSI(Private Set Intersection) Join**: 양측 암호화 해시 테이블의 일치점(Intersection)을 탐색하여, 원시 개인식별정보(PII) 누출 없이 데이터 셋을 병합(Merge).
3. **Pandas 폴백 지원**: Pandas 설치 환경에서는 최적화된 고속 DataFrame Inner-Join을 지원하고, 표준 라이브러리(Stdlib)만 존재하는 미설치 환경에서는 Dict 및 Set 연산으로 원활하게 스위칭되어 무중단 로직 실행 보증.

---

## 7. 테스트 및 검증 계획 (Verification & Testing Plan)

### 7.1 자동화 단위 테스트
* **API 단위 테스트**: `pytest`를 활용하여 `/api/readyz`, `/api/nodes`, `/api/deployments` API의 응답 코드 및 Pydantic 유효성 테스트 실행.
  ```bash
  cd app
  pytest tests/
  ```

### 7.2 인프라 스모크 테스트 (Smoke Test)
* **사일로 DinD 커넥션 확인**:
  ```bash
  # 각 사일로의 도커 엔진 통신 확인
  docker -H tcp://localhost:2371 info
  docker -H tcp://localhost:2372 info
  ```
* **MinIO 상태 점검**:
  `http://localhost:7002` (Silo 1 Console) 및 `http://localhost:7004` (Silo 2 Console)에 접속하여 버킷(Bucket) 생성 및 데이터 업로드 API 연동 검증.

### 7.3 연합학습 시나리오 검증
* **가중치 전송 및 FedAvg 완수 시나리오**:
  1. 가상의 로컬 데이터셋을 사일로 1, 2, 3의 MinIO 버킷에 배포.
  2. 배치 스케줄러를 가동하여 매 1분마다 로컬 학습 및 전송 배치 잡 트리거.
  3. 라운드가 올라가면서 글로벌 모델의 평가 손실(Loss)이 점차 감소하고 최종 모델 가입소 등록까지 예외 없이 진행되는지 확인.
