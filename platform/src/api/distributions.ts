import { apiGet, apiPost } from '@/api/client'
import type { DistributionOverview, DistributionPolicyInput } from '@/types/simulation'

const ROOT = '/api/monitoring/distributions'
export const fetchDistributionOverview = () => apiGet<DistributionOverview>(`${ROOT}/drift`)
export const persistDistributionPolicy = (value: DistributionPolicyInput) => apiPost(`${ROOT}/policies`, value)
export const chooseDistributionBaseline = (reportId: string) => apiPost(`${ROOT}/baselines`, { report_id: reportId })
export const acknowledgeDistributionAlert = (alertId: string) => apiPost(`${ROOT}/alerts/${encodeURIComponent(alertId)}/ack`)
