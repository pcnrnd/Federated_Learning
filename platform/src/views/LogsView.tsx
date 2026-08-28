import { LogConsole } from '@/components/logs/LogConsole'
import { LogFilters } from '@/components/logs/LogFilters'

export function LogsView() {
  return (
    <div className="tab-pane">
      <div className="glass-panel content-card full-card logs-full-panel">
        <div className="card-header-logs">
          <div className="logs-title-area">
            <h3>
              <i className="fa-solid fa-terminal" /> 시스템 연합 학습 오케스트레이터 실시간 로그
            </h3>
            <span className="desc">
              Filtering and monitoring global and private node communications.
            </span>
          </div>
          <LogFilters />
        </div>
        <div className="card-body no-padding overflow-hidden">
          <LogConsole />
        </div>
      </div>
    </div>
  )
}
