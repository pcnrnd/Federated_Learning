import { lineageKey, type LineageKind } from '@/api/retrainingLineage'
import { useRetrainingLineageStore } from '@/store/useRetrainingLineageStore'
import type { RetrainingEvent } from '@/types/simulation'

function Detail({ kind, id, label }: { kind: LineageKind; id: string; label: string }) {
  const detail = useRetrainingLineageStore((s) => s.entries[lineageKey(kind, id)])
  const load = useRetrainingLineageStore((s) => s.load)
  return <div><button type="button" className="btn btn-secondary" disabled={detail?.pending}
    onClick={() => { void load(kind, id) }}>{label} 상세</button>
    {detail?.pending && <p role="status">상세를 불러오는 중입니다.</p>}
    {detail?.error && <p role="alert">{detail.error}</p>}
    {detail?.lines.map((line) => <p key={line}>{line}</p>)}
  </div>
}
export function RetrainingLineage({ event }: { event: RetrainingEvent }) {
  return <details><summary>실행 계보</summary>
    <Detail kind="cleaning" id={event.cleaning_request.job_id} label="정제 작업" />
    <Detail kind="training" id={event.training_request.job_id} label="학습 작업" />
    {event.registered_model && <Detail kind="result" id={event.registered_model.round_id} label="최종 학습 결과" />}
  </details>
}
