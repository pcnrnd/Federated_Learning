# 계층형 사일로 토폴로지 + HFL 증설 설계

- 날짜: 2026-07-24
- 대상: `platform/` 시뮬레이션 SPA (구 `fed/` → `paltform/` → 현 `platform/`, rename 완료)
- 상태: 사용자 승인 완료 · **구현 완료** (vitest 포함)
- 위치: **`platform/`의 기준 설계 문서.** 계층 토폴로지·2단 집계·라운드 페이즈에 대한
  판단은 본 문서를 근거로 한다. `platform/`은 자체 백엔드 없이 동작하는 시뮬레이션이며
  실서버 연동은 읽기 전용 폴링([2026-08-21-p0-api-contract.md](./2026-08-21-p0-api-contract.md))에
  한정된다. 백엔드 대상 문서인
  [2026-08-21-hfl-server-design.md](./2026-08-21-hfl-server-design.md)는 `backup/poc2/`
  백엔드 PoC 기록물이므로 `platform/`의 기준이 아니다.

## 1. 배경과 목표

메인 대시보드의 "실시간 연합 네트워크" 화면은 현재 중앙 서버를 중심으로 12개 사일로가
원형(방사형)으로 배치된다. 이를 다음 요건에 맞는 계층 구조로 개선한다.

1. 최상위에 중앙 서버, 그 아래 1단에 **사일로 1~12가 전부** 한 줄로 배치된다.
2. 각 사일로 번호 아래에 **하위 노드를 증설**할 수 있다 (사일로별 확장).
3. 하위 노드는 표시 전용이 아니라 **계층형 연합학습(HFL)** 의 정식 참여자다:
   하위 노드가 로컬 학습 → 상위 사일로가 로컬(엣지) 집계 → 중앙 서버가 글로벌 집계.

## 2. 확정된 결정 사항 (Q&A 기록)

| 질문 | 결정 |
|------|------|
| 하위 노드의 역할 | **HFL 계층 집계** — 상위 사일로가 로컬 집계자 |
| 증설 조작 위치 | **기존 SiloRegisterForm 확장** — "상위 사일로(1~12)" 선택 추가. 토폴로지는 표시 전용 유지 |
| 하위 노드 표시 방식 | **상시 표시 + 자동 맞춤** — viewBox 동적 계산, SVG가 카드 폭에 자동 스케일 |
| 엔진 통합 깊이 | **풀 HFL 2단계 라운드** — 하위 노드도 NodeState 정식 참여자, 라운드에 엣지 집계 페이즈 추가 |
| 테스트 | **vitest 최소 구성** — 2단 집계·레이아웃 좌표 순수 함수만 |
| 계층 깊이 | **2단으로 제한** (서버 → 사일로 → 하위 노드). 하위의 하위는 미지원 |
| 1단 사일로 | 12개 고정, 삭제 불가. 신규 등록은 항상 하위 노드(parentId 필수) |

## 3. 리서치 근거 (요약)

- **HierFAVG** (Liu et al., "Client-Edge-Cloud Hierarchical Federated Learning", IEEE ICC 2020):
  클라이언트 → 엣지 집계자 → 클라우드의 3단 구조가 공인 패턴. 본 설계의
  하위 노드 → 사일로 → 서버 구조와 1:1 대응.
- **NVIDIA FLARE 2.7** "Hierarchical FLARE": 서버 → 릴레이 → 클라이언트 프록시 트리를
  프로덕션 제공, parent/child 용어 사용.
- 용어 권고: 하위는 "sub-silo"가 아닌 **노드/leaf client** 계열로 명명
  (사일로 = 조직 경계). UI 라벨: 하위 노드는 **"하위 노드"**, 하위를 가진 사일로에
  **"로컬 집계자"** 뱃지.
- 시각화 관례: 서버 상단, 집계자 중단, 리프 하단의 톱다운 트리.

참고: IEEE 9148862, nvflare.readthedocs.io (hierarchical_architecture),
flower.ai docs (SuperLink/SuperNode), Google Cloud cross-silo/cross-device FL 아키텍처.

## 4. 상세 설계

### 4.0 디렉터리 오타 정정 (완료)

- `paltform/` → `platform/` 파일시스템 rename. 당시 git 미추적이었으므로 rename 후 그대로 추가.
- 소스는 `@/` 별칭만 사용하므로 코드 수정 없음. `package.json`의 `name` 필드만 확인·정정.
- 로컬 CLAUDE.md의 `fed/` 참조를 `platform/`으로 갱신 (gitignore 대상, 커밋 안 됨).

### 4.1 데이터 모델

`src/types/simulation.ts`:

- `NodeState`에 `parentId?: number` 추가. `undefined` = 1단 사일로.
- `Silo`에 `parentId?: number` 추가 (리소스 탭 공유).
- `NodeStatus`에 `'aggregating'` 추가 (사일로 로컬 집계 상태).
- `PacketDirection`에 `'edge-download' | 'edge-upload'` 추가.
- `NewSiloInput`에 `parentId: number` 추가 (1~12 필수).

규칙:

- 1단 사일로 12개는 `SILO_SEEDS` 고정. `removeSilo`는 `parentId`가 있는 노드만 허용.
- 상위 사일로가 비활성(`enabled=false`)이면 그 하위 노드도 라운드에서 제외된다
  (경로가 끊기므로). 하위 노드 자체 토글도 기존과 동일하게 동작.
- `useSimulationStore.reset()`은 학습 상태만 초기화하고 **등록된 하위 노드는 유지**한다.
  구현: reset이 **자신의 `state.nodes`에서 `parentId` 있는 노드를 걸러 보존**(메트릭·상태만
  초기화)하고 1단만 `createInitialNodes()`로 재생성한다. nodeFactory가 siloStore를 읽는
  방식은 금지 — `useSiloStore → useSimulationStore` 기존 import에 역방향이 더해져
  순환 import(모듈 평가 시점 TDZ 크래시 위험)가 생긴다. (검증 에이전트 BLOCKER 반영)

### 4.2 스토어 연동

- `useSiloStore.addSilo(input)`: `parentId` 저장 + `useSimulationStore.addNode()`로
  학습 노드 전파 + 기존 `ensureSiloData()` 유지.
- `useSiloStore.removeSilo(id)`: `parentId` 없는 사일로(1단)는 거부.
  하위 노드 삭제 시 `useSimulationStore.removeNode()`·`removeSiloData()` 전파.
- `useSimulationStore`에 `addNode(node)` / `removeNode(id)` /
  `setNodeStatusByIds(ids, status)` 액션 추가 — 마지막 것은 3a 페이즈에서
  "하위=uploading, 상위=aggregating" 부분 집합별 상태 설정에 필요.
- 참여 판정 헬퍼 `effectiveEnabledNodes(nodes)`를 `src/lib/aggregation.ts`에 배치:
  자신이 enabled이고 (하위 노드라면) 상위도 enabled인 노드만 반환.
  현재 코드의 `n.enabled` 단독 판정 4곳(setAllNodeStatus/setAllNodeCpu/엔진 학습 필터/집계
  필터)을 이 헬퍼 기준으로 통일한다.
- `NewSiloInput`은 `useSiloStore.ts`에 정의되어 있음(types 파일 아님) — 그 자리에서 확장.
- 신규 하위 노드의 학습 파라미터(size/delay/mult)는 `nodeFactory`의 기존 랜덤 규칙 재사용.

### 4.3 토폴로지 레이아웃

`src/constants/simulation.ts`의 `TOPOLOGY`를 계층 상수로 교체하고,
`src/lib/topology.ts`가 노드 배열로부터 레이아웃을 계산한다.

```
                    [ 중앙 서버 ]                    y ≈ 50
      ╱ ╱ ╱ ╱ (베지어) ╲ ╲ ╲ ╲
  사일로1  사일로2  …  사일로11  사일로12            y ≈ 200  (12개 × 간격 ~80px)
    │                    │
   노드13               노드14                       y ≈ 300+ (부모 x 기준 세로 스택)
                        노드15
```

- viewBox 동적 계산: `width = 12 × 간격 + 여백`, `height = 기본 + 최대 하위 스택 깊이 × 간격`.
  SVG는 컨테이너 폭에 맞춰 자동 스케일 (`.topology-box` max-width 480px 제한 해제).
- 엣지 2종: 서버→사일로는 cubic bezier, 사일로→하위는 짧은 수직 연결.
- 패킷 애니메이션은 기존 `mpath` 방식 유지. 경로 id 체계:
  `path-node-{id}`(서버↔사일로), `path-edge-{childId}`(사일로↔하위).
- `edge-download`/`edge-upload` 페이즈에는 하위 경로에만 패킷을 흘린다.

### 4.4 엔진 — 2단계 HFL 라운드

`useSimulationEngine.runRound()`의 4페이즈를 6페이즈로 확장.
**하위 노드가 하나도 없으면 1b/3a는 스킵되어 기존 동작과 동일**하다.

| 페이즈 | 동작 | packetDirection |
|--------|------|------------------|
| 1 | 서버 → 사일로 브로드캐스트 (기존) | `download` |
| 1b | 사일로 → 하위 노드 배포 (하위 보유 사일로만) | `edge-download` |
| 2 | 전 노드(1단+하위) 로컬 학습 (기존 로직 그대로) | `local` |
| 3a | 하위 → 사일로 업로드, 해당 사일로 `aggregating` 상태 + 로그 "[사일로N] 로컬 집계 완료 (하위 k개)" | `edge-upload` |
| 3b | 사일로 → 서버 업로드 (기존) | `upload` |
| 4 | 글로벌 집계 (기존) | — |

- 집계(`src/lib/aggregation.ts`): `aggregateHierarchy(nodes, algorithm)` 신설 —
  ① `parentId`로 그룹핑해 엣지 가중평균(데이터 크기 `size` 가중) 반영,
  ② 1단 사일로에 대해 기존 `aggregate()` 재사용해 글로벌 집계.
- **엣지 집계의 참여 범위 = `[상위 자신, ...하위들]`.** 상위 사일로는 순수 집계자가
  아니라 **자신도 로컬 데이터로 학습하는 사일로**이므로(Phase 2가 1단까지 학습시키고,
  `nodeFactory`가 1단에도 `size`를 부여하며, 노드 카드가 1단의 로컬 데이터·정확도를
  표시한다) 자신의 기여를 엣지 평균에 포함하고, 상위의 글로벌 가중치는 `자신 + 하위`
  표본수 합이 된다. 이 정의에서 클러스터가 전 노드의 진짜 분할이 되어
  **계층 집계 결과 ≡ 평면 집계 결과**(가중평균 결합법칙)가 정확히 성립한다.
  상위를 제외하면 상위의 로컬 데이터가 글로벌 집계에서 조용히 사라진다.
- WAN 트래픽 집계는 **1단 사일로 수 기준 유지** (하위→상위는 사내망 취급, 과금 제외).
  주의: 현재 엔진은 `nodes.length`를 두 곳에서 사용 — 트래픽 계산(engine :130)과
  브로드캐스트 로그 "N개 사일로"(engine :62). 둘 다 `parentId === undefined` 필터 필수.
  학습 개시/업로드 안내 로그(`pickRandomIds`)도 하위 노드가 뽑히면 "사일로" 문구가
  어긋나므로 1단만 대상으로 하거나 문구를 "노드"로 조정.
- 엣지 페이즈 타이밍은 기존 `TIMINGS.downloadAnimationMs` 재사용 (신규 상수 최소화).
- `pathClass`(TopologySVG)는 현재 전역 direction을 모든 경로에 일괄 적용하므로
  경로별 분기 필요: 서버↔사일로 경로는 `download`/`upload`에만, 사일로↔하위 경로는
  `edge-download`/`edge-upload`에만 활성. `PacketDot`의 direction 리터럴 타입도 확장.

### 4.5 UI 변경

- `SiloRegisterForm`: "상위 사일로" select 추가 (사일로1~12, 필수).
- `SiloCard`: 하위 노드 카드에 상위 사일로 표시. 1단 카드에 하위 수 뱃지 +
  "로컬 집계자" 표기. 1단 카드의 삭제 버튼 제거.
- `NodeCard`(노드 탭): `aggregating` 상태 라벨 추가, 하위 노드는 상위 표시.
- `global.css`: `aggregating` 상태 스타일, 토폴로지 폭 제한 해제, 하위 노드용
  축소 노드 스타일.

### 4.6 에러 처리·엣지 케이스

| 케이스 | 동작 |
|--------|------|
| 하위 노드 0개 | 엣지 페이즈 스킵 — 기존 12노드 플로우와 동일 |
| 상위 사일로 비활성 | 하위 노드도 라운드 제외 (idle 유지) |
| 라운드 진행 중 증설 | 노드는 즉시 토폴로지에 나타나고 다음 라운드부터 학습 참여 |
| 라운드 진행 중 하위 삭제 | 다음 페이즈부터 제외 (엔진은 매 페이즈 스토어를 재조회) |
| reset | 하위 노드 유지, 학습 상태만 초기화 |
| 등록 폼 검증 | 이름 공백·parentId 미선택 시 제출 불가 (기존 폼 검증 관례 따름) |

## 5. 테스트 계획

- **vitest** (신규 devDependency, Vite 설정 공유):
  - `aggregation.test.ts`: 2단 가중평균 — 하위 있는/없는 사일로 혼재, 전원 비활성,
    가중치(size) 반영 검증. 손으로 계산한 기대값 대조.
  - `topology.test.ts`: 1단 12개 x 좌표 등간격·y 동일, 하위 노드가 부모 x에 정렬,
    viewBox가 하위 수에 따라 확장되는지 검증.
- `npm run typecheck`, `npm run build` 통과 (기존 게이트).
- UI는 dev 서버에서 육안 확인 (마크업 단위 테스트는 채택하지 않음).

## 6. 검증 계획

1. 설계 검증: 별도 세션 에이전트가 본 문서를 코드베이스와 대조해 실현 가능성·누락 검토.
2. 구현 후 code-reviewer 에이전트 리뷰 (CRITICAL/HIGH 즉시 수정).
3. typecheck + build + vitest 통과 확인 후 커밋.

## 7. 변경 파일 목록

| 파일 | 변경 |
|------|------|
| `paltform/` → `platform/` | 디렉터리 rename |
| `src/types/simulation.ts` | parentId, aggregating, edge 패킷 방향, NewSiloInput |
| `src/constants/simulation.ts` | TOPOLOGY 계층 상수 |
| `src/lib/topology.ts` | 계층 레이아웃·경로·viewBox 계산 |
| `src/lib/aggregation.ts` | aggregateHierarchy |
| `src/lib/nodeFactory.ts` | 하위 노드 생성 규칙 재사용 |
| `src/store/useSimulationStore.ts` | addNode/removeNode, reset 시 하위 유지 |
| `src/store/useSiloStore.ts` | parentId, 등록/삭제 전파·가드 |
| `src/hooks/useSimulationEngine.ts` | 1b/3a 페이즈 |
| `src/components/topology/TopologySVG.tsx` | 계층 렌더링, 엣지 패킷 |
| `src/components/silos/SiloRegisterForm.tsx` | 상위 사일로 select |
| `src/components/silos/SiloCard.tsx` | 뱃지·삭제 가드 |
| `src/components/nodes/NodeCard.tsx` | aggregating 라벨, 상위 표시 |
| `src/styles/global.css` | 상태·레이아웃 스타일 |
| `package.json` 외 | vitest 추가, 테스트 2파일 |

부수 정리(선택): 사용처 없는 `NODE_COUNT_REF` export 삭제,
`useSystemHeartbeat`의 "N/N" 문구는 1단 수 고정이라 그대로 유효.

## 8. 검증 이력

- 2026-07-24 설계 검증 에이전트(별도 세션) 대조 완료 — BLOCKER 1(순환 import),
  WARN 3(부모 비활성 메커니즘, nodes.length 오염, packetDirection 소비자), INFO 다수.
  전 항목 본 문서 4장에 반영됨. id 충돌 없음(siloSeq=13 시작), rename 전제(미추적) 확인.
