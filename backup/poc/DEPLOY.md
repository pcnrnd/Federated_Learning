# [DEPLOY.md] 분산형 데이터 연합컴퓨팅 플랫폼 PoC 배포 및 구동 가이드
(PoC Environment Deployment & Setup Guide)

본 문서는 **연합컴퓨팅 플랫폼 PoC** 환경을 로컬 또는 개발 서버에 정상적으로 구성하고 배포, 기동하기 위한 단계별 명령어와 가이드라인입니다.

---

## 1. 사전 준비 사항 (Prerequisites)

시스템을 구동하기 전에 설치 및 확인되어야 하는 종속성 패키지입니다.

* **운영체제**: Linux (Ubuntu 22.04 권장) 또는 Windows (WSL2 및 Docker Desktop 설치 환경)
* **도구**: 
  * Docker Engine v20.10+
  * Docker Compose v2.0+
  * Python 3.10+ (로컬 테스트 시)

---

## 2. 배포 및 구동 3단계 (Setup Steps)

FCP 백엔드 및 사일로들은 공동의 격리 네트워크인 `fed-net`을 통해 통신하므로, 네트워크 설정 및 사일로 구동 순서를 반드시 지켜야 합니다.

```
[1단계] 외부 네트워크 생성 (fed-net)
   └── [2단계] 격리 사일로 샌드박스 기동 (silo-1, silo-2, silo-3)
         └── [3단계] FCP 통합 대시보드 API 기동 (Host/Docker)
```

### 1단계: 외부 가상 네트워크 생성
중앙 대시보드 서버와 분산 사일로가 논리적으로 결합할 수 있는 외부 도커 네트워크를 먼저 수동 생성합니다.

```bash
docker network create fed-net
```

### 2단계: 물리 격리 사일로(Silo) 기동
`silo/` 디렉터리로 이동하여 특권 권한(Privileged)으로 DinD(Docker-in-Docker) 및 MinIO가 탑재된 사일로 3대를 백그라운드로 빌드 및 구동합니다.

```bash
cd silo
# silo-1, silo-2, silo-3 동시 빌드 및 백그라운드 기동
docker compose -f compose.silo.yaml up -d --build
```

* **구동 확인**:
  ```bash
  docker ps --filter "name=silo"
  ```
  * `silo-1`, `silo-2`, `silo-3` 컨테이너가 `Up` 상태이고, 각각 SSH(`2223~2225`), Docker TCP(`2371~2373`), MinIO API(`7001, 7003, 7005`) 포트가 호스트로 포워딩되어 있는지 확인합니다.

### 3단계: FCP 통합 대시보드 백엔드 기동

대시보드와 API 엔진은 두 가지 방식(도커 실행 또는 로컬 파이썬 실행) 중 선택하여 구동할 수 있습니다.

#### 옵션 A: Docker Compose로 실행 (권장)
설정이 간편하고 호스트 도커 소켓이 안전하게 바인딩되어 실행됩니다.

```bash
# node_management_v0,2 디렉토리로 이동
cd ../node_management_v0,2

# 대시보드 및 API 서버 빌드 및 기동
docker compose -f compose.dashboard.yaml up -d --build
```
* 대시보드 API는 호스트 포트 `8000`번으로 서비스됩니다.

#### 옵션 B: 로컬 개발 환경에서 실행 (No-Docker)
디버깅이 용이하고 코드를 실시간으로 수정하며 구동할 때 유용합니다.

```bash
# app 디렉토리로 이동 (3차년도 통합 플랫폼 대상)
cd ../app

# 가상환경 활성화 및 패키지 설치
pip install -r requirements.txt

# API 보안 키 설정 (선택 사항)
# Windows CMD: set FED_API_KEY=my_secure_secret
# PowerShell: $env:FED_API_KEY="my_secure_secret"
# Linux/bash: export FED_API_KEY="my_secure_secret"

# uvicorn 서버 구동 (app 디렉토리 내부에서 실행 시)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 3. 동작 상태 및 헬스 체크 (Health Check)

서비스가 정상 기동되었는지 브라우저 혹은 cURL 명령어를 통해 가볍게 진증합니다.

1. **프로세스 모니터링 경량 Probe (`healthz`)**
   ```bash
   curl http://localhost:8000/healthz
   # 기대 응답: {"status": "ok"}
   ```
2. **연합 컴퓨팅 컴포넌트 준비 상태 검증 (`readyz`)**
   ```bash
   curl http://localhost:8000/readyz
   # 기대 응답: 스케줄러 기동 여부, 설정 파일 디렉토리 쓰기 권한 등의 체크 항목 반환
   ```
3. **웹 대시보드 접속**
   * 브라우저에서 `http://localhost:8000/dashboard` 로 접속하여 메인 관제 UI가 정상 출력되는지 확인합니다.

---

## 4. 환경 초기화 및 종료 (Tear Down)

PoC 실증 시연이 끝난 후 시스템을 완전히 정리하는 방법입니다.

```bash
# FCP 대시보드 종료
cd node_management_v0,2
docker compose -f compose.dashboard.yaml down -v

# 격리 사일로 종료 및 생성된 내부 데이터 볼륨 영구 삭제
cd ../silo
docker compose -f compose.silo.yaml down -v

# 외부 네트워크 삭제
docker network rm fed-net
```
