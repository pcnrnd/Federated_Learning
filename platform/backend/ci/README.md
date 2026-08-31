# CI 파이프라인 템플릿

GitHub Actions 워크플로우와 lint 설정을 보관한다.
GitHub Actions는 저장소 루트의 `.github/workflows/` 디렉토리만 인식하므로 **본 파일을 그곳에 복사**해야 실제 트리거된다.

## 설치 (저장소 루트에서)

```bash
mkdir -p .github/workflows
cp app/ci/ci.yml .github/workflows/ci.yml
cp app/ci/ruff.toml ruff.toml      # 또는 pyproject.toml에 [tool.ruff] 섹션으로 병합
```

이후 PR/main push에서 자동 실행된다.

## 실행 내용

| Job | 단계 |
|---|---|
| **test** | Python 3.11/3.12 매트릭스 × pytest + pytest-cov (≥ 80% 강제) |
| **lint** | `ruff check` + `ruff format --check` |

테스트 커버리지 XML은 워크플로우 artifact로 업로드된다.

## 로컬에서 동일 검증

```bash
cd app

# 테스트 + 커버리지
pip install pytest pytest-asyncio pytest-cov
python -m pytest tests/ --cov=. --cov-fail-under=80 --cov-report=term-missing

# 린트
pip install 'ruff>=0.5.0'
ruff check .
ruff format --check .
```

## 커스터마이즈

- 배포 단계가 필요하면 `cd` 잡 추가 (예: Docker Hub push, K8s rollout)
- `paths` 필터로 `app/**` 변경 시에만 실행 — 다른 영역 작업 시 워크플로우가 안 돈다.
- 매트릭스 Python 버전은 `strategy.matrix.python-version` 에서 조정.
