# R&D 요구사항 추적성 (Traceability)

9개 연합컴퓨팅 R&D 작업 → API · 서비스 · 테스트 매핑.

| # | 요구사항 | API 라우트 (prefix) | 핵심 서비스 | 테스트 |
|---|---------|---------------------|------------|--------|
| P0-1 | 모델 패키징·배포 | `/api/models`, `/api/packaging`, `/api/deployments` | `model_registry`, `packaging_service`, `deployment_service`, `deployment_strategies` | `test_model_registry.py`, `test_packaging_service.py`, `test_deployment_service.py`, `test_e2e_scenarios.py` |
| P0-2 | 모델 모니터링 | `/api/monitoring` | `metric_store`, `drift_detector`, `alert_service`, `prometheus_exporter` | `test_metric_store.py`, `test_drift_detector.py`, `test_alert_service.py`, `test_prometheus_exporter.py` |
| P1-1 | 사일로 링크·파라미터 수집 | `/api/silo-groups`, `/api/training-rounds` | `silo_group_service`, `training_round_service`, `fedavg_aggregator`, `round_scheduler` | `test_silo_groups.py`, `test_training_round.py`, `test_fedavg.py`, `test_round_scheduler.py`, `test_e2e_scenarios.py` |
| P1-2 | Batch Scheduling | `/api/training-jobs` | `training_job_service`, `round_scheduler` | `test_training_job.py`, `test_round_scheduler.py` |
| P1-3 | 리소스 모니터링 | `/api/resources` | `resource_service` | `test_resource_service.py`, `test_api_phase2.py` |
| P1-4 | 모델 유지관리 | `/api/lineage`, `/api/shadow`, `/api/ab-tests` | `lineage_service`, `shadow_deployment_service`, `ab_test_service` | `test_lineage_service.py`, `test_shadow_deployment.py`, `test_ab_test_service.py` |
| P1-5 | 데이터 정제 | `/api/cleaning-recipes`, `/api/cleaning-jobs` | `cleaning_recipe_service`, `cleaning_job_service`, `cleaning_recipes` | `test_cleaning_recipe.py`, `test_cleaning_job.py`, `test_sdk_cleaning.py` |
| P2-1 | 사일로 데이터 시각화 (5종 KPI) | `/api/visualizations` | `visualization_service` | `test_visualization_service.py`, `test_dashboard_endpoint.py` |
| P2-2 | 비동기 I/O·통합 대시보드 | `/api/dashboard`, `/dashboard` | `async_io`, `visualization_service` | `test_async_io.py`, `test_dashboard_endpoint.py`, `test_dashboard_e2e.py` |

## 횡단 관심사

| 관심사 | 구현 | 테스트 |
|--------|------|--------|
| 저장소 (YAML/SQLite) | `storage/*`, `config/*_manager` | `test_storage_repository.py` |
| API Key | `main.py` middleware, `FED_API_KEY` | `test_api_auth_integration.py`, `test_runtime_operations.py` |
| 멱등성 | `services/idempotency.py`, `X-Idempotency-Key` | `test_api_phase2.py` |
| 페이지네이션 | `models/common_schemas.PaginatedResponse` | `test_api_phase2.py` |
| 사일로 SDK | `silo_sdk/client.py`, `async_client.py` | `test_silo_sdk.py`, `test_async_silo_client.py` |
| CI 스모크 | `.github/workflows/ci.yml` | `test_runtime_operations.py`, `test_dashboard_e2e.py` |

## E2E 시나리오 (TestClient, 사일로 불필요)

| 시나리오 | 파일 | 검증 흐름 |
|---------|------|----------|
| 학습 라운드 | `test_e2e_scenarios.py::test_e2e_training_round_lifecycle` | register → group → round → contribute → metrics → aggregate |
| 모델 배포 | `test_e2e_scenarios.py::test_e2e_model_register_version_deploy_rollback` | register v1/v2 → deploy → rollback |
