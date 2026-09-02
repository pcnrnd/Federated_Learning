# CI 파이프라인

실제 워크플로우는 저장소 루트 **`.github/workflows/ci.yml`** 하나다 (GitHub Actions는 그 위치만 인식).
이 디렉터리에는 아직 게이트에 넣지 않은 lint 설정 템플릿만 남긴다.

## 워크플로우 구성 (`.github/workflows/ci.yml`)

| Job | 작업 디렉터리 | 단계 |
|---|---|---|
| **backend-test** | `platform/backend` | Python 3.11/3.12 × pytest + pytest-cov (≥ 80% 강제), coverage.xml artifact |
| **backend-smoke** | `platform/backend` | TestClient 스모크 (`test_runtime_operations`, `test_dashboard_e2e`, `test_api_auth_integration`) |
| **backend-lint** | `platform/backend` | `ruff check` (ruff 기본 규칙) |
| **frontend** | `platform` | `npm ci` → `tsc --noEmit` → `vitest run` |

트리거: `platform/backend/**`, `platform/src/**`, 프론트 빌드 설정, `platform/compose.yaml`, 워크플로우 자신.

## `ruff.toml` (템플릿, 미적용)

`platform/backend` 루트에 복사하면 isort·bugbear·pyupgrade 규칙과 포맷 규칙이 켜진다.
현재 CI 게이트는 **ruff 기본 규칙의 `ruff check`만** 강제한다 — `ruff format --check`와 확장 규칙은
전 파일 일괄 수정(100+ 파일)이 필요해 diff 추적성을 위해 별도 결정 사항으로 보류했다.

## 로컬에서 동일 검증

```bash
cd platform/backend
pip install -r requirements-dev.txt
python -m pytest tests/ --cov=. --cov-fail-under=80 --cov-report=term-missing
ruff check .

cd ../    # platform/
npm ci && npm run typecheck && npm test
```
