import { useEffect, useMemo, useRef } from 'react'
import { useSimulationStore } from '@/store/useSimulationStore'
import type { LogEntry, LogFilter, LogKind } from '@/types/simulation'

function shouldShow(entry: LogEntry, filter: LogFilter): boolean {
  if (filter === 'all') return true
  if (filter === 'system') return entry.kind === 'system'
  if (filter === 'server') {
    return entry.kind === 'server' || entry.kind === 'success' || entry.kind === 'error'
  }
  if (filter === 'nodes') return entry.kind === 'client'
  return true
}

function tagFor(entry: LogEntry): string {
  if (entry.kind === 'system') return '[SYSTEM]'
  if (entry.kind === 'server') return '[SERVER]'
  if (entry.kind === 'success') return '[SUCCESS]'
  if (entry.kind === 'error') return '[ERROR]'
  if (entry.kind === 'client' && entry.nodeId !== undefined) {
    return `[NODE ${entry.nodeId}]`
  }
  return '[LOG]'
}

function kindClass(kind: LogKind): string {
  return kind
}

export function LogConsole() {
  const logs = useSimulationStore((s) => s.logs)
  const filter = useSimulationStore((s) => s.logFilter)
  const scrollerRef = useRef<HTMLDivElement | null>(null)

  const visible = useMemo(() => logs.filter((e) => shouldShow(e, filter)), [logs, filter])

  useEffect(() => {
    const el = scrollerRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [visible])

  return (
    <div className="console-box">
      <div ref={scrollerRef} className="console-log-expanded">
        {visible.map((entry) => (
          <div key={entry.id} className={`log-entry ${kindClass(entry.kind)}`}>
            <span className="time">[{entry.time}]</span>
            <span className="tag">{tagFor(entry)}</span>
            <span className="msg">{entry.message}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
