# Federated Learning project of PCN RND

## 프로젝트 개요

이 프로젝트는 Federated Learning 환경을 구축하고 관리하기 위한 시스템입니다. 여러 노드(서버)를 중앙에서 관리하고, 각 노드의 컨테이너를 모니터링 및 제어할 수 있는 웹 대시보드를 제공합니다.

## 주요 구성 요소

### 1. Node Management (노드 관리 시스템)
- **기능**:
  - 여러 Docker 서버(노드)의 중앙 관리
  - 노드별 컨테이너 목록 조회 및 상태 모니터링
  - 컨테이너 시작/중지/재시작 제어
  - 웹 대시보드를 통한 시각화 (그래프 뷰, 서버 뷰)
  - 노드 추가/수정/삭제 및 연결 테스트

### 2. Silo (격리된 학습 환경)
- **기능**:
  - Federated Learning 클라이언트를 위한 격리된 Docker 환경 제공
  - 각 Silo는 독립된 Docker 데몬을 실행 (데이터 격리)
  - SSH 및 Docker API 접근 지원
  - 최대 6개의 Silo 환경 구성 가능

## 프로젝트 구조

```
Federated_Learning/
├── node_management/          # 노드 관리 시스템
│   ├── app/
│   │   ├── api/              # API 엔드포인트 (노드, 컨테이너)
│   │   ├── config/           # 설정 관리
│   │   ├── models/           # 데이터 모델
│   │   ├── services/         # Docker 서비스 로직
│   │   └── main.py           # FastAPI 애플리케이션 진입점
│   ├── static/               # 정적 파일 (CSS, JS)
│   └── templates/            # HTML 템플릿
└── silo/                     # Silo 환경 구성
    ├── Dockerfile.silo       # Silo 컨테이너 이미지 정의
    ├── compose.silo.yaml     # Docker Compose 설정
    └── entrypoint.sh         # 컨테이너 시작 스크립트
```

## 주요 기능

- **다중 노드 관리**: 여러 서버를 하나의 대시보드에서 관리
- **컨테이너 모니터링**: 실시간 컨테이너 상태 조회 및 제어
- **격리된 학습 환경**: 각 Federated Learning 클라이언트를 위한 독립된 Silo 환경
- **웹 기반 UI**: 직관적인 웹 인터페이스를 통한 관리
