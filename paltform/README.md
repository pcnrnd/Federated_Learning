# Federated Computing Orchestrator (React)

연합컴퓨팅 오케스트레이터 및 대시보드 — 분산 노드의 연합학습(Federated Learning) 라운드를
시각적으로 시뮬레이션하는 단일 페이지 애플리케이션입니다.

> `_legacy/`에 vanilla v0.1 (HTML/CSS/JS) 원본을 보관합니다.

## 기술 스택


| 영역     | 사용 기술                                 |
| ------ | ------------------------------------- |
| 빌드     | Vite 6 (HMR / 번들 / `tsc -b`)          |
| 프레임워크  | React 18                              |
| 언어     | TypeScript 5 (strict)                 |
| 상태 관리  | Zustand 5 (단일 진실의 원천)                 |
| 차트     | Chart.js 4 + react-chartjs-2          |
| 스타일    | 순수 CSS (글래스모피즘 디자인 시스템)               |
| 폰트/아이콘 | Inter · Outfit · Font Awesome 6 (CDN) |


## 빠른 시작

```bash
npm install
npm run dev        # http://localhost:5173
npm run typecheck  # tsc --noEmit
npm run build      # tsc -b && vite build → dist/
npm run preview    # build 결과 미리보기
```

> 모듈 경로는 `@/` 별칭(`tsconfig.json` + `vite.config.ts`)으로 `src/`를 가리킵니다.
> 예: `import { aggregate } from '@/lib/aggregation'`

## 구조

```
src/
├── main.tsx                # React 진입점
├── App.tsx                 # 탭 라우팅 (VIEW_REGISTRY)
├── styles/global.css       # 글래스모피즘 디자인 시스템 (v0.1 보존)
├── types/simulation.ts     # 도메인 타입 (Algorithm, TabId, Node 등)
├── constants/simulation.ts # NODE_COUNT, TOPOLOGY, TIMINGS, 알고리즘 메타
├── lib/
│   ├── topology.ts         # 노드 좌표 계산 (순수)
│   ├── aggregation.ts      # FedAvg / Median / SecAgg 집계 (순수)
│   ├── nodeFactory.ts      # 초기 노드 생성
│   └── format.ts           # 포맷 유틸
├── store/useSimulationStore.ts  # Zustand: 단일 상태 소스
├── hooks/useSimulationEngine.ts # 라운드 오케스트레이션 + 취소 가능
├── components/
│   ├── layout/             # Sidebar, GlobalHeader, AppLayout
│   ├── topology/           # SVG 토폴로지 + 패킷 애니메이션
│   ├── controls/           # 시뮬레이션 컨트롤 패널 + 슬라이더
│   ├── nodes/              # 노드 카드
│   ├── analytics/          # Chart.js 성능 차트
│   └── logs/               # 로그 콘솔 + 필터
└── views/                  # 탭별 컨테이너 (Dashboard / Nodes / Analytics / Logs)
```

## 데이터 흐름

```
ControlPanel ──dispatch──▶ useSimulationStore (Zustand)
                                  │  상태 변경
                                  ▼
useSimulationEngine ──라운드 사이클──▶ store 업데이트(불변)
                                  │
                                  ▼
        Views/Components ◀──구독── store (상태 → 선언형 JSX)
```

- **단일 진실의 원천**: 모든 시뮬레이션 상태는 Zustand store에 모입니다.
- **순수 로직 분리**: 집계·토폴로지·포맷은 `lib/`의 순수 함수로, 렌더링과 독립적입니다.
- **안전한 취소**: 엔진은 세대(generation) 토큰으로 진행 중인 라운드를 안전하게 중단합니다.

## 기능

- 12개 분산 노드 + 중앙 서버 토폴로지 (SVG)
- 4개 탭 (메인 대시보드 / 분산 노드 관리 / 성능 분석 / 실시간 로그)
- 3개 집계 알고리즘
  - **FedAvg** — 연합 가중 평균
  - **Federated Median** — 이상치에 견고
  - **Secure Aggregation** — 암호 보안 합산 (트래픽 비용 ↑)
- 라운드 / 로컬 에폭 / 학습률 슬라이더 + 알고리즘 선택
- 다운로드 → 학습 → 업로드 → 집계 4단계 사이클 애니메이션
- 실시간 차트 (정확도 + 손실 이중축)
- 로그 콘솔 + 4가지 필터 (전체 / 시스템 / 서버 / 노드)
- 시작 / 일시정지 / 초기화 + 재시작 흐름

## 설정값

주요 상수는 `src/constants/simulation.ts`에 집중되어 있습니다.


| 상수                            | 값                                        | 설명          |
| ----------------------------- | ---------------------------------------- | ----------- |
| `NODE_COUNT`                  | 12                                       | 분산 노드 수     |
| `DEFAULT_CONFIG.totalRounds`  | 15                                       | 기본 학습 라운드   |
| `DEFAULT_CONFIG.localEpochs`  | 5                                        | 노드별 로컬 에폭   |
| `DEFAULT_CONFIG.learningRate` | 0.01                                     | 기본 학습률      |
| `CONFIG_BOUNDS`               | rounds 5–50 / epochs 1–10 / lr 0.001–0.1 | 슬라이더 범위     |
| `TRAFFIC_PER_NODE_MB`         | fedavg/median 1.15, secagg 2.25          | 노드당 통신량(MB) |




