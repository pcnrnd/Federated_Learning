# TASKS.md — 미구현 화면 진행현황

> 휘발성 상태(완료/다음/결정)만 관리하는 living 문서. **스펙·규약은 [DESIGN.md](./DESIGN.md)** 참조.
> 화면별 상세 명세는 `DESIGN.md §6.x`, 완료 기준 체크리스트도 거기 있음.

## 클로드 앱(claude.ai)에서 작업하는 법

1. Claude **Project**를 만들고 `DESIGN.md` + `TASKS.md`를 **프로젝트 지식에 업로드**.
2. 화면 1개씩 요청: `DESIGN §6.2 구현해줘. 6.1 ModelRegistry 패턴/규약을 그대로 따라.`
3. 받은 코드를 로컬 레포에 반영 → **로컬에서 검증**: `cd fed && npm run typecheck && npm run build`.
4. 통과하면 아래 상태표 갱신 + 커밋 (`feat: <화면명>`).

> 클로드 앱은 레포를 직접 읽거나 빌드를 못 돌림. 검증은 항상 로컬에서.

## 상태 범례

✅ 완료 · 🔄 진행중 · ⬜ 대기

## 진행 상태

| # | 화면 | 출처 | 새 위치 | 상태 |
|---|------|------|---------|------|
| 6.1 | 모델 버전관리 | 그림 66 | `models` 탭 | ✅ |
| 6.2 | 모델 패키징·배포 관리 | 그림 67 | `models` 탭 내 섹션 | ✅ |
| 6.6 | 사일로 리소스 모니터링 + 등록 | 그림 88 | `silos` 탭 | ✅ |
| 6.4 | 사일로 데이터 정제·샤딩 | 그림 79 | `data` 탭 | ✅ |
| 6.5 | 배치 스케줄러 | 그림 80 | `data` 탭 내 섹션 | ✅ |
| 6.3 | 모델 모니터링 | — | `analytics` 확장 | ✅ |

## 다음 작업

🎉 **DESIGN.md §6 화면 전부 구현 완료.** 남은 미구현 화면 없음.

## 완료 기록

- **6.1 모델 버전관리** — `useModelStore`(목 7건) + `ModelsView`/`ModelRegistry`/`NewModelForm`,
  탭 라우팅 5곳 연결, 배포·롤백·보관·삭제, 공유 로그 콘솔 연동. typecheck/build 통과.
- **6.2 모델 패키징·배포 관리** — `useModelStore`에 `packages`/`deployments` 슬라이스 + `buildPackage`/`createDeployment`/`rollbackDeployment`
  추가. `models` 탭 하위 섹션으로 `DeploymentSection`(+`PackagingCard`/`StrategyForm`/`DeploymentTimeline`).
  배포 전략 3종(일괄·주기 / 실시간 / 에지·노드 다중선택), `setTimeout` 목 진행 `대기→배포중→완료`,
  롤백, 공유 로그 연동. typecheck/build 통과 + dev 육안 확인.
- **6.6 사일로 리소스 모니터링 + 등록** — `useSiloStore`(목 3건) + `silos` 탭(`SilosView`/`SiloCard`/`SiloRegisterForm`).
  CPU/메모리/디스크 바 + 임계값 마커·초과 경보, 임계값 인라인 편집, 등록 폼. 탭 라우팅 5곳 연결.
- **6.4 사일로 데이터 정제·샤딩 + 6.5 배치 스케줄러** — `useDataStore`(siloData 3건 + jobs 5건) + `data` 탭(`DataView`).
  정제율 카드(`CleansingGrid`) + 샤딩 박스 다이어그램(`ShardingDiagram`) + 스케줄러(`JobScheduler`: 의존성 게이팅·병렬 실행·일시중지).
- **6.3 모델 모니터링** — `useSimulationStore`에 `monitorPoints` + 엔진 라운드별 처리량/처리시간/드리프트 생성.
  `AnalyticsView`에 `MonitorChart`(이중축) + `DriftCard`(임계 경보) 추가.
  ⚠️ Chart.js `maintainAspectRatio:false` 캔버스 무한 성장 버그 → `.analytics-chart-box` 고정 높이(420px)로 해결.

## 개선 작업 (기획 §6 이후 보강)

검토 결과 일부 화면이 모니터링 위주여서 제어·연동을 보강함 (DESIGN §6 범위 외 추가):

- **데이터 파이프라인 인과 연결** — 6.4 정제 카드에 사일로별 `정제 실행` 버튼(목 진행 0→100%),
  6.5 `데이터 정제(Cleanse)` 작업 완료 시 전 사일로 정제율 100% 갱신. (`useDataStore.cleanseSilo` + job 연동)
- **store 통합·전파** — 사일로 식별자를 `useSiloStore` 단일 소스로 통일. `useDataStore`는 `dataBySilo`(siloId 키)로
  파이프라인 수치만 보유. silos 탭 등록/해제가 data 탭(정제 카드·샤드 다이어그램)에 즉시 전파.
- **nodes 탭 목 제어** — `NodeState.enabled` 추가 + `toggleNode`/`restartNode`. 비활성 노드는 학습/집계 제외
  (엔진 `enabled` 필터). 카드에 활성/비활성·재시작 버튼, 비활성 시 dim + DISABLED 배지.
- **드리프트→재학습 연동** — 6.3 `DriftCard`에 `재학습 트리거` 버튼(주의/임계초과 시). 클릭 시
  `useModelStore.triggerRetrain`이 운영 모델의 신규 실험 버전(vX.Y+1) 생성 + models 탭 이동.

typecheck/build 통과, dev 4기능 육안 확인.

## 파이프라인 등록 (6.5 보강)

검토 결과 스케줄러 작업이 고정 5개 + 전역 단계라 "사일로에 파이프라인 등록" 기능이 없었음
(노션 §6.5는 실행/일시중지만 명시 → 스펙 밖). **사일로별 파이프라인 등록(B안)** 으로 보강:

- `Job.targetSiloId?` 추가 (없으면 '전체' 공통 단계). `useDataStore.addJob`/`removeJob`.
- `PipelineRegisterForm` — 대상 사일로 / 작업명 / 스케줄(cron) / 선행 의존성(칩 다중선택).
- `JobScheduler`에 `파이프라인 등록` 버튼 + **대상 사일로 컬럼** + 행별 삭제. 의존성·병렬·실행/정지 로직 재사용.
- 삭제 시 다른 작업의 `dependsOn`에서도 자동 제거.

## 사일로·노드 용어 통합 (A안 — 12개 사일로 단일 정체성)

검토 결과 `nodes`(학습 참여자 12)와 `silos`(리소스 3)가 같은 주체를 서로 다른 개수·개념으로
다뤄 용어가 혼용됐음. 제품 컨셉이 **"12개 사일로가 전처리 → 연합학습 → 중앙서버 배포 수신"**
(cross-silo FL)이므로 **사일로 = 노드 = 데이터 보유자 = 배포 대상**으로 일원화:

- **단일 정의 소스** `SILO_SEEDS`(constants, 12개: id/name/shortName/endpoint/수집주기/cpu·mem·disk).
  엔진 노드(`nodeFactory`)·`useSiloStore`·`useDataStore`가 같은 id·이름을 공유.
- **개수 통일**: 사일로 3 → **12**, 데이터 파이프라인 시드도 12로. 학습 노드(12)와 1:1.
- **배포 흐름 = 중앙서버 → 12 사일로**: `Deployment.targetNodeIds → targetSiloIds`,
  `StrategyForm` 대상 선택을 `useSiloStore` 사일로로, 전략 `에지 배포 → 선택 배포`
  (실시간=전체 사일로 / 일괄=전체+주기 / 선택=일부 사일로). 타임라인·로그 scope "사일로 N곳".
- **용어 통일(UI 문자열)**: `nodes` 탭 "분산 노드 관리 → 사일로 학습 현황", 카드 제목 "사일로명 (학습 사일로)",
  토폴로지 라벨 `shortName`(병원A·금융B…), 엔진/로그 "노드 → 사일로", 로그 태그 `[NODE] → [SILO]`,
  로그 필터 "분산 노드 → 사일로".
- **엔진 내부 식별자**(`nodes`/`NodeState`/`toggleNode`)는 리스크 최소화 위해 유지하되
  "사일로의 학습 런타임"으로 타입 주석에 명시. (전면 식별자 리네이밍은 후속 과제로 분리 가능)

typecheck/build 통과. dev 육안 확인: 토폴로지 12 사일로, 학습/리소스/정제 카드 각 12,
선택 배포 칩 12, 배포 E2E "선택 배포 · 사일로 2곳".

## UX 결정 — models 탭 레이아웃

"버전관리 / 패키징·배포를 서브탭으로 분리"를 검토했으나 **스택 유지 + 연결 보강**으로 결정.
이유: ① `data`·`analytics` 탭도 동일한 "카드 2개 스택" 패턴이라 models만 서브탭이면 일관성 깨짐,
② 버전관리→배포는 순차 의존 워크플로라 분리 시 맥락 단절. 대신 다음을 추가:

- 탭 상단 **앵커 네비**(버전관리 / 패키징·배포 점프 링크, `scrollToElement`)
- 레지스트리 행 **`패키징·배포`** 버튼 → 배포 섹션으로 스크롤 + 해당 모델 자동 선택
  (선택 상태를 `useModelStore.deployTargetId`로 승격해 교차 선택 가능)
- **용어 중복 해소**: 레지스트리 행 `배포` → `운영 전환`(상태 플립), 섹션은 `배포 실행`(패키징·전략) 유지

## 결정 사항 (Decisions)

- **백엔드 없음**: 모든 데이터는 Zustand store의 목 데이터. 실 API는 범위 밖.
- **톤앤매너 유지**: 노션 그림과 시각적 모방 X. 기존 CSS 토큰/유틸 클래스만 재사용, 새 색/라운드 도입 금지.
- **로그 연동**: 화면 액션은 `useSimulationStore.getState().log()`로 실시간 로그 탭에 기록 (6.1에서 확립한 패턴).
- **새 화면 = 새 탭**: `DESIGN.md §4`의 5곳 수정 패턴 준수.
