import { apiGet, apiPost } from '@/api/client'
import type { RetrainingConfig, RetrainingConfigInput, RetrainingEvent, RetrainingOverview } from '@/types/simulation'

const ROOT = '/api/monitoring/distributions/retraining'
export const fetchRetraining = () => apiGet<RetrainingOverview>(ROOT)
export const saveRetraining = (body: RetrainingConfigInput) => apiPost<RetrainingConfig>(`${ROOT}/configs`, body)
export const runRetraining = (retrainConfigId: string, requestId: string) => apiPost<RetrainingEvent>(`${ROOT}/events`,
  { retrain_config_id: retrainConfigId, request_id: requestId })
export const retryRetraining = (eventId: string) => apiPost<RetrainingEvent>(`${ROOT}/events/${encodeURIComponent(eventId)}/retry`)
