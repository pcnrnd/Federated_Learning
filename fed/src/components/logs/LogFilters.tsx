import { useSimulationStore } from '@/store/useSimulationStore'
import type { LogFilter } from '@/types/simulation'

const FILTERS: Array<{ value: LogFilter; label: string }> = [
  { value: 'all', label: '전체 로그' },
  { value: 'system', label: '시스템' },
  { value: 'server', label: '중앙 서버' },
  { value: 'nodes', label: '분산 노드' },
]

export function LogFilters() {
  const logFilter = useSimulationStore((s) => s.logFilter)
  const setLogFilter = useSimulationStore((s) => s.setLogFilter)
  const clearLogs = useSimulationStore((s) => s.clearLogs)

  return (
    <div className="log-filter-controls">
      <div className="filter-group">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            className={`filter-btn${logFilter === f.value ? ' active' : ''}`}
            onClick={() => setLogFilter(f.value)}
          >
            {f.label}
          </button>
        ))}
      </div>
      <button
        type="button"
        className="btn-clear-large"
        title="콘솔 전체 삭제"
        onClick={clearLogs}
      >
        <i className="fa-solid fa-trash-can" /> 콘솔 초기화
      </button>
    </div>
  )
}
