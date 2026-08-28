import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { FilterBar } from './components/FilterBar';
import { MetricChartCard } from './components/charts/MetricChartCard';
import { InteractiveHeatmap } from './components/charts/InteractiveHeatmap';
import { PulseTopology } from './components/charts/PulseTopology';

const API_KEY_STORAGE_KEY = 'fed-dashboard-api-key';

interface Alert {
  alert_id?: string;
  rule_id: string;
  model_name?: string;
  version?: string;
  metric?: string;
  message?: string;
  status?: string;
  observed_value?: number;
  threshold?: number;
  triggered_at?: string;
}

interface SiloUsage {
  silo_id: string;
  cpu_pct: number;
  mem_pct: number;
  over_budget: boolean;
}

interface ModelItem {
  name: string;
  version: string;
  framework: string;
  weights_path: string;
  created_at: string;
}

interface SiloGroup {
  group_id: string;
  member_node_ids: string[];
  description?: string;
  tags?: string[];
  updated_at: string;
}

interface Deployment {
  deployment_id: string;
  model_name: string;
  version: string;
  strategy: string;
  target_node_ids: string[];
  status: string;
  created_at: string;
}

const App: React.FC = () => {
  // --- States ---
  const [modelsData, setModelsData] = useState<{ [key: string]: string[] }>({});
  const [modelList, setModelList] = useState<string[]>([]);
  const [versionList, setVersionList] = useState<string[]>([]);

  const [selectedModel, setSelectedModel] = useState('');
  const [selectedVersion, setSelectedVersion] = useState('');
  const [selectedMetric, setSelectedMetric] = useState('accuracy');
  const [selectedResource, setSelectedResource] = useState('cpu_pct');
  const [feature, setFeature] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [isMock, setIsMock] = useState(false); // 데모 모킹 모드 스위치

  // Charts & Ops States
  const [dashboardData, setDashboardData] = useState<any>(null);
  const [opsData, setOpsData] = useState<{
    models: ModelItem[];
    groups: SiloGroup[];
    deployments: Deployment[];
    usage: SiloUsage[];
    alerts: Alert[];
  }>({ models: [], groups: [], deployments: [], usage: [], alerts: [] });

  const [opsState, setOpsState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [showAuthBanner, setShowAuthBanner] = useState(false);
  const [selectedDetail, setSelectedDetail] = useState<{ title: string; rows: [string, string][] } | null>(null);

  // 실시간 보간 상태 저장을 위한 ref
  const mockStateRef = useRef<any>(null);

  // --- Fetch API Helper ---
  const fetchJSON = async (url: string) => {
    const headers: HeadersInit = {};
    if (apiKey) headers['X-FED-API-Key'] = apiKey;
    const res = await fetch(url, { headers });
    if (res.status === 401 || res.status === 403) {
      setShowAuthBanner(true);
      throw new Error('인증 오류');
    }
    setShowAuthBanner(false);
    if (!res.ok) throw new Error(`${url} 호출 실패`);
    return res.json();
  };

  // --- Initial Loading ---
  useEffect(() => {
    const savedKey = sessionStorage.getItem(API_KEY_STORAGE_KEY) || '';
    setApiKey(savedKey);

    const initModels = async () => {
      if (isMock) {
        // 모킹 시 가짜 모델 정보 즉시 시딩
        const byName = { 'demo-alpha': ['1.0.0', '1.1.0', '2.0.0'], 'fed-bert': ['1.0.0'] };
        setModelsData(byName);
        setModelList(Object.keys(byName));
        setSelectedModel('demo-alpha');
        setVersionList(byName['demo-alpha']);
        setSelectedVersion('1.0.0');
        return;
      }

      try {
        const models = await fetchJSON('/api/models');
        const byName: { [key: string]: string[] } = {};
        models.forEach((m: any) => {
          (byName[m.name] ||= []).push(m.version);
        });
        setModelsData(byName);
        const names = Object.keys(byName);
        setModelList(names);
        if (names.length > 0) {
          setSelectedModel(names[0]);
          setVersionList(byName[names[0]] || []);
          setSelectedVersion(byName[names[0]]?.[0] || '');
        }
      } catch (e) {
        console.error(e);
      }
    };
    initModels();
  }, [isMock]);

  // API Key 변경 시 스토리지 저장
  useEffect(() => {
    if (apiKey) {
      sessionStorage.setItem(API_KEY_STORAGE_KEY, apiKey);
    } else {
      sessionStorage.removeItem(API_KEY_STORAGE_KEY);
    }
  }, [apiKey]);

  // 모델 바뀔 때 버전 리스트 연계 갱신
  const handleModelChange = (model: string) => {
    setSelectedModel(model);
    const versions = modelsData[model] || [];
    setVersionList(versions);
    if (versions.length > 0) {
      setSelectedVersion(versions[0]);
    } else {
      setSelectedVersion('');
    }
  };

  // --- 실시간 모킹 데이터 생성 및 난수 Wave 연산 ---
  const generateMockData = () => {
    const silos = ['silo-1', 'silo-2', 'silo-3', 'silo-4', 'silo-5', 'silo-6'];

    if (!mockStateRef.current || mockStateRef.current.model !== selectedModel || mockStateRef.current.ver !== selectedVersion) {
      // 1. 시계열 메트릭
      const series: { [key: string]: { timestamp: string; value: number }[] } = {};
      const timestamps = ['10:00', '10:10', '10:20', '10:30'];
      silos.forEach((s, idx) => {
        const base = 0.76 + idx * 0.02;
        series[s] = timestamps.map((ts, tIdx) => ({
          timestamp: ts,
          value: base + tIdx * 0.015 + (Math.random() - 0.5) * 0.005,
        }));
      });

      // 2. 바 차트 리소스
      const items = silos.map((s, idx) => ({
        silo_id: s,
        value: 32 + idx * 7 + Math.random() * 5,
      }));

      // 3. 히트맵
      const heatmap = {
        row_labels: silos,
        col_labels: ['accuracy', 'latency_ms', 'throughput_rps'],
        matrix: silos.map((s, idx) => [
          0.82 + idx * 0.012,
          125.0 - idx * 4,
          52.0 + idx * 3.5,
        ]),
      };

      // 4. 토폴로지
      const topology = {
        nodes: [
          { id: 'demo-six-silos', label: 'demo-six-silos', role: 'group' },
          ...silos.map((s) => ({ id: s, label: `데모 사일로 ${s.slice(-1)}`, role: 'silo', over_budget: s === 'silo-6' })),
          { id: 'deploy::demo-alp', label: `${selectedModel}@${selectedVersion}`, role: 'deployment' },
        ],
        edges: silos.map((s) => ({ source: 'demo-six-silos', target: s, kind: 'group' })),
      };

      // 5. 히스토그램
      const histogram = {
        bin_edges: [0, 20, 40, 60, 80, 100],
        bin_counts: [14, 25, 38, 18, 5],
      };

      mockStateRef.current = {
        model: selectedModel,
        ver: selectedVersion,
        timeseries: { series },
        silo_bar_resource: { items },
        heatmap,
        topology,
        histogram,
      };
    } else {
      // 기존 모킹 데이터에 2초 실시간 출렁거림(Wave) 보간
      const state = mockStateRef.current;
      
      // Line차트 마지막 포인트 파동
      Object.keys(state.timeseries.series).forEach((silo) => {
        const arr = state.timeseries.series[silo];
        const last = arr[arr.length - 1];
        last.value = Math.max(0.1, Math.min(1.0, last.value + (Math.random() - 0.5) * 0.007));
      });

      // 리소스 바 차트
      state.silo_bar_resource.items.forEach((it: any) => {
        it.value = Math.max(10, Math.min(100, it.value + (Math.random() - 0.5) * 4));
      });

      // 히트맵
      state.heatmap.matrix.forEach((row: any) => {
        row[0] = Math.max(0.5, Math.min(1.0, row[0] + (Math.random() - 0.5) * 0.004));
        row[1] = Math.max(10, row[1] + (Math.random() - 0.5) * 1.5);
        row[2] = Math.max(5, row[2] + (Math.random() - 0.5) * 1.0);
      });

      // 6번 사일로 상태 주기적 펄스 변동
      const s6 = state.topology.nodes.find((n: any) => n.id === 'silo-6');
      if (s6 && Math.random() < 0.2) {
        s6.over_budget = !s6.over_budget;
      }
    }

    return mockStateRef.current;
  };

  const getMockOpsData = () => {
    return {
      models: [
        { name: 'demo-alpha', version: '1.0.0', framework: 'pytorch', weights_path: '/srv/weights/demo_alpha_v1.pth', created_at: '2026-05-26T08:24:02Z' },
        { name: 'demo-alpha', version: '1.1.0', framework: 'pytorch', weights_path: '/srv/weights/demo_alpha_v1_1.pth', created_at: '2026-05-26T09:12:00Z' },
        { name: 'fed-bert', version: '1.0.0', framework: 'tensorflow', weights_path: '/srv/weights/fed_bert.h5', created_at: '2026-05-26T05:44:00Z' },
      ],
      groups: [
        { group_id: 'demo-six-silos', member_node_ids: ['silo-1', 'silo-2', 'silo-3', 'silo-4', 'silo-5', 'silo-6'], description: '데모용 6개 사일로 그룹', updated_at: '2026-05-26T08:24:02Z' },
      ],
      deployments: [
        { deployment_id: 'deploy::demo-alp', model_name: selectedModel || 'demo-alpha', version: selectedVersion || '1.0.0', strategy: 'realtime', target_node_ids: ['silo-1', 'silo-2', 'silo-3', 'silo-4', 'silo-5', 'silo-6'], status: 'running', created_at: '2026-05-26T08:24:02Z' },
      ],
      usage: [
        { silo_id: 'silo-1', cpu_pct: 31.0 + Math.random() * 3, mem_pct: 36.0, over_budget: false },
        { silo_id: 'silo-2', cpu_pct: 37.0 + Math.random() * 3, mem_pct: 40.0, over_budget: false },
        { silo_id: 'silo-3', cpu_pct: 43.0 + Math.random() * 3, mem_pct: 44.0, over_budget: false },
        { silo_id: 'silo-4', cpu_pct: 49.0 + Math.random() * 3, mem_pct: 48.0, over_budget: false },
        { silo_id: 'silo-5', cpu_pct: 55.0 + Math.random() * 3, mem_pct: 52.0, over_budget: false },
        { silo_id: 'silo-6', cpu_pct: 61.0 + Math.random() * 3, mem_pct: 56.0, over_budget: mockStateRef.current?.topology?.nodes.find((n: any) => n.id === 'silo-6')?.over_budget || false },
      ],
      alerts: [
        { rule_id: 'silo-6-cpu-pressure', model_name: selectedModel || 'demo-alpha', version: selectedVersion || '1.0.0', metric: 'cpu_pct', message: 'silo-6 CPU 자원 임계값 80% 초과 우려', status: 'open', observed_value: 82.5, threshold: 80.0, triggered_at: '2026-05-26T10:28:44Z' },
      ],
    };
  };

  // --- Refresh / Load Dashboard Data ---
  const handleRefresh = async () => {
    if (!selectedModel || !selectedVersion) return;
    setOpsState('loading');

    if (isMock) {
      // 1. Mock Dashboard 데이터 로드
      const dash = generateMockData();
      setDashboardData({ ...dash });

      // 2. Mock Ops 현황 로드
      const ops = getMockOpsData();
      setOpsData(ops);
      setOpsState('ready');
      setShowAuthBanner(false);
      return;
    }

    const params = new URLSearchParams({
      model_name: selectedModel,
      version: selectedVersion,
      metric: selectedMetric,
      resource_metric: selectedResource,
    });
    if (feature.trim()) params.set('feature', feature.trim());

    try {
      const dash = await fetchJSON(`/api/dashboard?${params}`);
      setDashboardData(dash);

      const [models, groups, deployments, usage, alertsRaw] = await Promise.all([
        fetchJSON('/api/models'),
        fetchJSON('/api/silo-groups'),
        fetchJSON('/api/deployments'),
        fetchJSON('/api/resources/usage'),
        fetchJSON('/api/monitoring/alerts?limit=20'),
      ]);
      const alerts = Array.isArray(alertsRaw) ? alertsRaw : alertsRaw.items || [];
      setOpsData({ models, groups, deployments, usage, alerts });
      setOpsState('ready');
    } catch (e) {
      console.error(e);
      setOpsState('error');
    }
  };

  // 파라미터 변경 시 자동 새로고침 트리거
  useEffect(() => {
    if (selectedModel && selectedVersion) {
      handleRefresh();
    }
  }, [selectedModel, selectedVersion, selectedMetric, selectedResource, isMock]);

  // --- 2초 실시간 모킹 타이머 루프 (Wave) ---
  useEffect(() => {
    let timer: NodeJS.Timeout | null = null;
    if (isMock && selectedModel && selectedVersion) {
      timer = setInterval(() => {
        const dash = generateMockData();
        setDashboardData({ ...dash });
        const ops = getMockOpsData();
        setOpsData(ops);
      }, 2000);
    }
    return () => {
      if (timer) clearInterval(timer);
    };
  }, [isMock, selectedModel, selectedVersion]);

  const activePressureCount = opsData.usage.filter((u) => u.over_budget).length;

  return (
    <div className="relative min-h-screen pb-10">
      {/* Background Ambient Glows */}
      <div className="bg-glow bg-glow-1"></div>
      <div className="bg-glow bg-glow-2"></div>

      {/* Header bar */}
      <header className="flex justify-between items-center px-8 py-4 bg-[#0f172a]/70 backdrop-blur-[24px] border-b border-white/5 sticky top-0 z-50">
        <h1 className="text-xl font-extrabold bg-gradient-to-r from-accent to-[#818cf8] bg-clip-text text-transparent tracking-tighter">
          연합컴퓨팅 플랫폼
        </h1>
        <nav>
          <a
            href="/docs"
            target="_blank"
            className="text-muted hover:text-text bg-white/5 border border-white/5 rounded-full px-4 py-2 text-xs font-semibold shadow-inner transition-all hover:bg-accent/10 hover:border-accent hover:shadow-glow-cyan"
          >
            API Specification
          </a>
        </nav>
      </header>

      {/* Filter panel */}
      <FilterBar
        models={modelList}
        versions={versionList}
        selectedModel={selectedModel}
        selectedVersion={selectedVersion}
        selectedMetric={selectedMetric}
        selectedResource={selectedResource}
        feature={feature}
        apiKey={apiKey}
        isMock={isMock}
        onModelChange={handleModelChange}
        onVersionChange={setSelectedVersion}
        onMetricChange={setSelectedMetric}
        onResourceChange={setSelectedResource}
        onFeatureChange={setFeature}
        onApiKeyChange={setApiKey}
        onMockToggle={(val) => {
          setIsMock(val);
          if (!val) {
            mockStateRef.current = null;
          }
        }}
        onRefresh={handleRefresh}
      />

      {/* Auth Banner */}
      {showAuthBanner && !isMock && (
        <div className="flex items-center justify-between gap-4 mx-8 mt-5 p-3.5 border border-danger/30 rounded-xl bg-danger/5 text-red-300 text-xs backdrop-blur-md">
          <span>
            API Key가 필요합니다. 상단에 <code>FED_API_KEY</code>를 입력한 뒤 재시도하세요.
          </span>
          <button
            onClick={handleRefresh}
            className="bg-danger text-bg px-4 py-1.5 rounded-full font-bold transition hover:shadow-glow-red hover:brightness-95"
          >
            재시도
          </button>
        </div>
      )}

      {/* Detail Drawer */}
      <AnimatePresence>
        {selectedDetail && (
          <motion.aside
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 300, damping: 25 }}
            className="mx-8 mt-5 border border-white/5 rounded-2xl bg-[#0f172a]/85 backdrop-blur-[28px] shadow-2xl overflow-hidden"
          >
            <div className="flex items-center justify-between px-5 py-3 bg-[#1e293b]/90 border-b border-white/5">
              <h2 className="text-sm font-extrabold text-accent">{selectedDetail.title}</h2>
              <button
                onClick={() => setSelectedDetail(null)}
                className="text-muted hover:text-text text-xl p-1 rounded-full hover:bg-white/5 transition-all"
              >
                &times;
              </button>
            </div>
            <div className="p-5 text-xs text-muted grid gap-2.5">
              {selectedDetail.rows.map(([label, val]) => (
                <div key={label} className="flex gap-4 border-b border-white/5 pb-2 last:border-0 last:pb-0">
                  <dt className="min-w-[110px] font-bold text-muted">{label}</dt>
                  <dd className="font-mono text-text font-medium">{val ?? '—'}</dd>
                </div>
              ))}
            </div>
          </motion.aside>
        )}
      </AnimatePresence>

      {/* Main Grid */}
      <main className="grid grid-cols-1 lg:grid-cols-2 gap-6 p-8">
        <motion.article
          whileHover={{ y: -8, scale: 1.01 }}
          transition={{ type: 'spring', stiffness: 300, damping: 20 }}
          className="glass-panel rounded-card p-6 min-h-[360px] flex flex-col cursor-default"
        >
          <h2 className="text-sm font-bold text-accent mb-4 tracking-tight">
            1. 메트릭 추이 <small className="text-muted font-medium ml-2 bg-white/5 px-2 py-0.5 rounded-full text-[10px]">timeseries</small>
          </h2>
          <MetricChartCard type="timeseries" timeseriesData={dashboardData?.timeseries} />
        </motion.article>

        <motion.article
          whileHover={{ y: -8, scale: 1.01 }}
          transition={{ type: 'spring', stiffness: 300, damping: 20 }}
          className="glass-panel rounded-card p-6 min-h-[360px] flex flex-col cursor-default"
        >
          <h2 className="text-sm font-bold text-accent mb-4 tracking-tight">
            2. 분포 <small className="text-muted font-medium ml-2 bg-white/5 px-2 py-0.5 rounded-full text-[10px]">histogram</small>
          </h2>
          <MetricChartCard type="histogram" histogramData={dashboardData?.histogram} />
        </motion.article>

        <motion.article
          whileHover={{ y: -8, scale: 1.01 }}
          transition={{ type: 'spring', stiffness: 300, damping: 20 }}
          className="glass-panel rounded-card p-6 min-h-[360px] flex flex-col cursor-default"
        >
          <h2 className="text-sm font-bold text-accent mb-4 tracking-tight">
            3. 사일로별 리소스 <small className="text-muted font-medium ml-2 bg-white/5 px-2 py-0.5 rounded-full text-[10px]">silo_bar</small>
          </h2>
          <MetricChartCard type="bar" barData={dashboardData?.silo_bar_resource} />
        </motion.article>

        <motion.article
          whileHover={{ y: -8, scale: 1.01 }}
          transition={{ type: 'spring', stiffness: 300, damping: 20 }}
          className="glass-panel rounded-card p-6 min-h-[360px] flex flex-col cursor-default"
        >
          <h2 className="text-sm font-bold text-accent mb-4 tracking-tight">
            4. 사일로 &times; 메트릭 <small className="text-muted font-medium ml-2 bg-white/5 px-2 py-0.5 rounded-full text-[10px]">heatmap</small>
          </h2>
          <InteractiveHeatmap payload={dashboardData?.heatmap} />
        </motion.article>

        <motion.article
          whileHover={{ y: -8, scale: 1.01 }}
          transition={{ type: 'spring', stiffness: 300, damping: 20 }}
          className="glass-panel rounded-card p-6 min-h-[360px] flex flex-col lg:col-span-2 cursor-default"
        >
          <h2 className="text-sm font-bold text-accent mb-4 tracking-tight">
            5. 토폴로지 <small className="text-muted font-medium ml-2 bg-white/5 px-2 py-0.5 rounded-full text-[10px]">topology</small>
          </h2>
          <PulseTopology payload={dashboardData?.topology} />
        </motion.article>

        {/* Operations Panel */}
        <motion.article
          whileHover={{ y: -8, scale: 1.005 }}
          transition={{ type: 'spring', stiffness: 300, damping: 20 }}
          className="glass-panel rounded-card p-6 lg:col-span-2 min-h-[300px]"
        >
          <h2 className="text-sm font-bold text-accent mb-4 tracking-tight">
            운영 현황 <small className="text-muted font-medium ml-2 bg-white/5 px-2 py-0.5 rounded-full text-[10px]">read-only</small>
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-5">
            <section className="border border-white/5 rounded-2xl bg-[#1e293b]/30 min-h-[220px] overflow-hidden flex flex-col">
              <h3 className="m-0 px-4 py-3 text-xs font-extrabold text-text bg-[#1e293b]/80 border-b border-white/5 uppercase tracking-wider">
                모델
              </h3>
              <div className="p-2 overflow-y-auto flex-1 max-h-[240px]">
                {opsState === 'loading' && <div className="text-xs text-muted p-3">불러오는 중…</div>}
                {opsState === 'ready' && opsData.models.slice(0, 8).map((m) => (
                  <div
                    key={`${m.name}@${m.version}`}
                    onClick={() => setSelectedDetail({
                      title: `모델 ${m.name}@${m.version}`,
                      rows: [['프레임워크', m.framework], ['가중치', m.weights_path], ['등록', m.created_at]],
                    })}
                    className="p-3 border-b border-white/[0.03] text-xs rounded-lg hover:bg-accent/10 hover:border-accent cursor-pointer transition"
                  >
                    <div className="text-text font-bold">{m.name}@{m.version}</div>
                    <div className="text-muted text-[10px]">{m.framework} · {m.created_at}</div>
                  </div>
                ))}
              </div>
            </section>

            <section className="border border-white/5 rounded-2xl bg-[#1e293b]/30 min-h-[220px] overflow-hidden flex flex-col">
              <h3 className="m-0 px-4 py-3 text-xs font-extrabold text-text bg-[#1e293b]/80 border-b border-white/5 uppercase tracking-wider">
                사일로 그룹
              </h3>
              <div className="p-2 overflow-y-auto flex-1 max-h-[240px]">
                {opsState === 'loading' && <div className="text-xs text-muted p-3">불러오는 중…</div>}
                {opsState === 'ready' && opsData.groups.slice(0, 8).map((g) => (
                  <div
                    key={g.group_id}
                    onClick={() => setSelectedDetail({
                      title: `그룹 ${g.group_id}`,
                      rows: [
                        ['멤버', g.member_node_ids.join(', ')],
                        ['설명', g.description || '-'],
                        ['태그', (g.tags || []).join(', ') || '-'],
                        ['갱신', g.updated_at],
                      ],
                    })}
                    className="p-3 border-b border-white/[0.03] text-xs rounded-lg hover:bg-accent/10 hover:border-accent cursor-pointer transition"
                  >
                    <div className="text-text font-bold">{g.group_id}</div>
                    <div className="text-muted text-[10px]">{g.member_node_ids.length} silos · {g.description || '-'}</div>
                  </div>
                ))}
              </div>
            </section>

            <section className="border border-white/5 rounded-2xl bg-[#1e293b]/30 min-h-[220px] overflow-hidden flex flex-col">
              <h3 className="m-0 px-4 py-3 text-xs font-extrabold text-text bg-[#1e293b]/80 border-b border-white/5 uppercase tracking-wider">
                배포
              </h3>
              <div className="p-2 overflow-y-auto flex-1 max-h-[240px]">
                {opsState === 'loading' && <div className="text-xs text-muted p-3">불러오는 중…</div>}
                {opsState === 'ready' && opsData.deployments.slice(0, 8).map((d) => (
                  <div
                    key={d.deployment_id}
                    onClick={() => setSelectedDetail({
                      title: `배포 ${d.deployment_id.slice(0, 8)}`,
                      rows: [
                        ['모델', `${d.model_name}@${d.version}`],
                        ['전략', d.strategy],
                        ['상태', d.status],
                        ['노드', d.target_node_ids.join(', ')],
                        ['생성', d.created_at],
                      ],
                    })}
                    className="p-3 border-b border-white/[0.03] text-xs rounded-lg hover:bg-accent/10 hover:border-accent cursor-pointer transition"
                  >
                    <div className="text-text font-bold">{d.model_name}@{d.version}</div>
                    <div className="text-muted text-[10px] flex items-center justify-between">
                      <span>{d.strategy} · {d.target_node_ids.length} nodes</span>
                      <span className={`badge ${d.status === 'running' ? 'ok' : 'warn'}`}>{d.status}</span>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className="border border-white/5 rounded-2xl bg-[#1e293b]/30 min-h-[220px] overflow-hidden flex flex-col">
              <h3 className="m-0 px-4 py-3 text-xs font-extrabold text-text bg-[#1e293b]/80 border-b border-white/5 uppercase tracking-wider">
                알림
              </h3>
              <div className="p-2 overflow-y-auto flex-1 max-h-[240px] flex flex-col gap-1">
                {opsState === 'loading' && <div className="text-xs text-muted p-3">불러오는 중…</div>}
                {opsState === 'ready' && (
                  <>
                    <div className="p-3 border-b border-white/[0.03] text-xs rounded-lg flex items-center justify-between font-semibold">
                      <span>리소스 압박</span>
                      <span className={`badge ${activePressureCount ? 'warn' : 'ok'}`}>
                        {activePressureCount}/{opsData.usage.length} silos
                      </span>
                    </div>

                    {opsData.usage.slice(0, 6).map((u) => (
                      <div
                        key={u.silo_id}
                        className="p-2.5 border-b border-white/[0.02] text-[11px] rounded flex justify-between items-center"
                      >
                        <span className="font-mono text-muted">{u.silo_id}</span>
                        <div className="flex items-center gap-2">
                          <span className="text-muted">CPU {u.cpu_pct.toFixed(1)} · MEM {u.mem_pct.toFixed(1)}</span>
                          <span className={`badge ${u.over_budget ? 'warn' : 'ok'}`}>
                            {u.over_budget ? 'over' : 'ok'}
                          </span>
                        </div>
                      </div>
                    ))}

                    {opsData.alerts.slice(0, 5).map((a) => (
                      <div
                        key={a.alert_id}
                        onClick={() => setSelectedDetail({
                          title: `알림 ${a.alert_id?.slice(0, 8) || ''}`,
                          rows: [
                            ['규칙', a.rule_id],
                            ['모델', a.model_name ? `${a.model_name}@${a.version || ''}` : '-'],
                            ['관측값', a.observed_value != null ? String(a.observed_value) : '-'],
                            ['임계값', a.threshold != null ? String(a.threshold) : '-'],
                            ['발화', a.triggered_at || '-'],
                          ],
                        })}
                        className="p-3 border-b border-white/[0.03] text-xs rounded-lg hover:bg-accent/10 hover:border-accent cursor-pointer transition"
                      >
                        <div className="text-text font-bold">{a.metric || a.rule_id}</div>
                        <div className="text-muted text-[10px] flex justify-between items-center">
                          <span>{a.model_name} · {a.message}</span>
                          <span className="badge warn">{a.status || 'open'}</span>
                        </div>
                      </div>
                    ))}
                  </>
                )}
              </div>
            </section>
          </div>
        </motion.article>
      </main>

      {/* Footer */}
      <footer className="py-6 text-center text-muted border-t border-white/5 bg-[#0f172a]/85 text-xs">
        5종 차트 · 단일 <code>GET /api/dashboard</code> 요청으로 병렬 컴포지션 및 100% 자체 독자 브랜드 포털 시각화
      </footer>
    </div>
  );
};

export default App;
