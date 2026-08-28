import React from 'react';

interface FilterBarProps {
  models: string[];
  versions: string[];
  selectedModel: string;
  selectedVersion: string;
  selectedMetric: string;
  selectedResource: string;
  feature: string;
  apiKey: string;
  isMock: boolean;
  onModelChange: (model: string) => void;
  onVersionChange: (version: string) => void;
  onMetricChange: (metric: string) => void;
  onResourceChange: (resource: string) => void;
  onFeatureChange: (feature: string) => void;
  onApiKeyChange: (key: string) => void;
  onMockToggle: (val: boolean) => void;
  onRefresh: () => void;
}

export const FilterBar: React.FC<FilterBarProps> = ({
  models,
  versions,
  selectedModel,
  selectedVersion,
  selectedMetric,
  selectedResource,
  feature,
  apiKey,
  isMock,
  onModelChange,
  onVersionChange,
  onMetricChange,
  onResourceChange,
  onFeatureChange,
  onApiKeyChange,
  onMockToggle,
  onRefresh,
}) => {
  return (
    <section className="flex flex-wrap gap-4 p-5 bg-opacity-35 backdrop-blur-md bg-[#0f172a] border-b border-white/5 items-end justify-start rounded-b-2xl shadow-lg">
      <label className="flex flex-col text-[11px] font-bold text-muted gap-1.5 uppercase tracking-wider">
        모델
        <select
          value={selectedModel}
          onChange={(e) => onModelChange(e.target.value)}
          className="bg-[#1e293b]/55 text-text border border-white/5 rounded-[10px] px-3 py-2 text-xs outline-none focus:border-accent focus:shadow-glow-cyan min-w-[160px]"
        >
          {models.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col text-[11px] font-bold text-muted gap-1.5 uppercase tracking-wider">
        버전
        <select
          value={selectedVersion}
          onChange={(e) => onVersionChange(e.target.value)}
          className="bg-[#1e293b]/55 text-text border border-white/5 rounded-[10px] px-3 py-2 text-xs outline-none focus:border-accent focus:shadow-glow-cyan min-w-[120px]"
        >
          {versions.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col text-[11px] font-bold text-muted gap-1.5 uppercase tracking-wider">
        메트릭
        <select
          value={selectedMetric}
          onChange={(e) => onMetricChange(e.target.value)}
          className="bg-[#1e293b]/55 text-text border border-white/5 rounded-[10px] px-3 py-2 text-xs outline-none focus:border-accent focus:shadow-glow-cyan min-w-[140px]"
        >
          <option value="accuracy">accuracy</option>
          <option value="latency_ms">latency_ms</option>
          <option value="throughput_rps">throughput_rps</option>
        </select>
      </label>

      <label className="flex flex-col text-[11px] font-bold text-muted gap-1.5 uppercase tracking-wider">
        리소스
        <select
          value={selectedResource}
          onChange={(e) => onResourceChange(e.target.value)}
          className="bg-[#1e293b]/55 text-text border border-white/5 rounded-[10px] px-3 py-2 text-xs outline-none focus:border-accent focus:shadow-glow-cyan min-w-[140px]"
        >
          <option value="cpu_pct">CPU %</option>
          <option value="mem_pct">Memory %</option>
          <option value="gpu_pct">GPU %</option>
          <option value="disk_pct">Disk %</option>
        </select>
      </label>

      <label className="flex flex-col text-[11px] font-bold text-muted gap-1.5 uppercase tracking-wider">
        드리프트 feature
        <input
          type="text"
          value={feature}
          placeholder="(선택)"
          onChange={(e) => onFeatureChange(e.target.value)}
          className="bg-[#1e293b]/55 text-text border border-white/5 rounded-[10px] px-3 py-2 text-xs outline-none focus:border-accent focus:shadow-glow-cyan min-w-[140px]"
        />
      </label>

      <label className="flex flex-col text-[11px] font-bold text-muted gap-1.5 uppercase tracking-wider">
        API Key
        <input
          type="password"
          value={apiKey}
          placeholder="FED_API_KEY"
          autoComplete="off"
          onChange={(e) => onApiKeyChange(e.target.value)}
          className="bg-[#1e293b]/55 text-text border border-white/5 rounded-[10px] px-3 py-2 text-xs outline-none focus:border-accent focus:shadow-glow-cyan min-w-[140px]"
        />
      </label>

      {/* iOS style Switch Toggle for Demo Mode in React */}
      <label className="flex flex-col text-[11px] font-bold text-muted gap-1.5 uppercase tracking-wider cursor-pointer select-none">
        데모 시뮬레이션
        <div
          onClick={() => onMockToggle(!isMock)}
          className={`relative w-12 h-[26px] rounded-full border transition-all duration-300 ${
            isMock
              ? 'bg-accent/25 border-accent shadow-glow-cyan'
              : 'bg-[#1e293b]/45 border-white/5'
          }`}
        >
          <div
            className={`absolute top-[3px] left-[3px] h-[18px] w-[18px] rounded-full transition-all duration-300 ${
              isMock
                ? 'translate-x-[24px] bg-accent shadow-[0_0_8px_#38bdf8]'
                : 'bg-muted'
            }`}
          />
        </div>
      </label>

      <button
        onClick={onRefresh}
        className="bg-accent-grad text-bg font-extrabold text-xs px-5 py-2.5 rounded-full hover:scale-105 active:scale-95 shadow-glow-cyan transition duration-300"
      >
        새로고침
      </button>
    </section>
  );
};
