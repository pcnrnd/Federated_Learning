# [API_SPEC.md] 분산형 데이터 연합컴퓨팅 플랫폼 API 명세서
(PoC RESTful API Specification)

본 문서는 **연합컴퓨팅 플랫폼 PoC**가 지원하는 핵심 RESTful API 인터페이스와 입출력 데이터 명세입니다.

---

## 1. 전역 설정 및 인증 보안 (Security & Auth)

모든 API 엔드포인트는 `FED_API_KEY` 환경변수가 백엔드 서버에 세팅되어 있는 경우, 반드시 **`X-FED-API-Key`** 커스텀 헤더를 포함하여 요청해야 합니다.

* **인증 헤더 예시**:
  ```http
  X-FED-API-Key: my_secure_secret
  Content-Type: application/json
  ```
* **인증 실패 응답 (`401 Unauthorized`)**:
  ```json
  {
    "detail": "유효한 API Key가 필요합니다",
    "code": "unauthorized"
  }
  ```

---

## 2. 노드 및 컨테이너 관리 API (`node_management`)

### 2.1 신규 노드 등록
* **Endpoint**: `POST /api/nodes`
* **요청 바디 (JSON)**:
  ```json
  {
    "base_url": "tcp://localhost:2371",
    "label": "의료 정보 사일로 A",
    "tls": false
  }
  ```
* **성공 응답 (`201 Created`)**:
  ```json
  {
    "node_id": "silo_1",
    "base_url": "tcp://localhost:2371",
    "label": "의료 정보 사일로 A",
    "type": "remote",
    "role": "client",
    "tls": false,
    "status": "connected"
  }
  ```
  *(참고: `type`과 `role`은 서버에서 동적 검증 후 자동으로 할당됩니다)*

### 2.2 노드 컨테이너 상태 제어
* **Endpoint**: `POST /api/nodes/{node_id}/containers/{container_id}/action`
* **요청 바디 (JSON)**:
  ```json
  {
    "action": "start" 
  }
  ```
  *(가용 action: `"start"`, `"stop"`, `"restart"`)*
* **성공 응답 (`200 OK`)**:
  ```json
  {
    "node_id": "silo_1",
    "container_id": "minio-silo1",
    "action": "start",
    "status": "success",
    "current_state": "running"
  }
  ```

---

## 3. 모델 수명주기 및 배포 API (`deployments`, `packaging`)

### 3.1 신규 연합 인공지능 모델 패키징 등록
* **Endpoint**: `POST /api/models`
* **요청 바디 (JSON)**:
  ```json
  {
    "model_name": "disease_predictor",
    "version": "v1.2.0",
    "framework": "pytorch",
    "description": "3개 기관 연합 심혈관 질환 분류 모델"
  }
  ```
* **성공 응답 (`201 Created`)**:
  ```json
  {
    "model_id": "md_9a8b7c6d",
    "model_name": "disease_predictor",
    "version": "v1.2.0",
    "framework": "pytorch",
    "status": "packaged",
    "created_at": "2026-05-27T00:58:00Z"
  }
  ```

### 3.2 모델 섀도우 배포 실행
* **Endpoint**: `POST /api/deployments`
* **요청 바디 (JSON)**:
  ```json
  {
    "model_id": "md_9a8b7c6d",
    "target_nodes": ["silo_1", "silo_2", "silo_3"],
    "deployment_mode": "shadow"
  }
  ```
  *(가용 mode: `"standard"`, `"shadow"`, `"ab_test"`)*
* **성공 응답 (`202 Accepted`)**:
  ```json
  {
    "deployment_id": "dep_1a2b3c",
    "model_id": "md_9a8b7c6d",
    "mode": "shadow",
    "status": "deploying",
    "active_endpoints": {
      "silo_1": "tcp://localhost:2371/predict-shadow",
      "silo_2": "tcp://localhost:2372/predict-shadow",
      "silo_3": "tcp://localhost:2373/predict-shadow"
    }
  }
  ```

---

## 4. 연합학습 및 파라미터 수합 API (`silo_groups`, `training_rounds`)

### 4.1 연합학습 사일로 그룹화
* **Endpoint**: `POST /api/silo-groups`
* **요청 바디 (JSON)**:
  ```json
  {
    "group_name": "종합병원_심혈관_연합망",
    "member_nodes": ["silo_1", "silo_2", "silo_3"]
  }
  ```
* **성공 응답 (`200 OK`)**:
  ```json
  {
    "group_id": "sg_cardio",
    "group_name": "종합병원_심혈관_연합망",
    "member_count": 3,
    "status": "ready"
  }
  ```

### 4.2 연합 가중치(파라미터) 제출 (사일로 ➡️ 중앙 FCP)
* **Endpoint**: `POST /api/rounds/{round_id}/parameters`
* **요청 바디 (JSON)**:
  ```json
  {
    "node_id": "silo_1",
    "sample_size": 1250,
    "weights": {
      "layer1.weight": 0.4582,
      "layer1.bias": -0.1024,
      "layer2.weight": 0.8921
    }
  }
  ```
* **성공 응답 (`200 OK`)**:
  ```json
  {
    "round_id": "rd_05",
    "node_id": "silo_1",
    "status": "accepted",
    "received_at": "2026-05-27T00:58:30Z"
  }
  ```

---

## 5. 데이터 정제 API (`cleaning_recipes`, `cleaning_jobs`)

### 5.1 데이터 정제 잡(Cleaning Job) 트리거
* **Endpoint**: `POST /api/cleaning-jobs`
* **요청 바디 (JSON)**:
  ```json
  {
    "recipe_id": "rec_clean_v1",
    "target_nodes": ["silo_1", "silo_2"],
    "parameters": {
      "impute_value": 0.0,
      "remove_duplicates": true
    }
  }
  ```
* **성공 응답 (`202 Accepted`)**:
  ```json
  {
    "job_id": "job_cln_5566",
    "recipe_id": "rec_clean_v1",
    "status": "running",
    "triggered_at": "2026-05-27T00:58:45Z"
  }
  ```
