import '@/test/currentSnapshotSsr'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { LiveDriftCard, LiveDriftSettings } from '@/components/analytics/LiveDrift'
import { draftForPolicy, driftScopeKey, emptyDriftDraft } from '@/lib/distributionDrift'
import { useSimulationStore } from '@/store/useSimulationStore'
import type { DistributionAlert, DistributionOverview, DistributionPolicy, DriftObservation } from '@/types/simulation'
import { useMonitoringStore as store } from './useMonitoringStore'

const { fetch, save, baseline, ack } = vi.hoisted(() => ({ fetch: vi.fn(), save: vi.fn(), baseline: vi.fn(), ack: vi.fn() }))
vi.mock('@/api/client', () => ({ isLiveConfigured: () => true }))
vi.mock('@/api/distributions', () => ({ fetchDistributionOverview: fetch, persistDistributionPolicy: save,
  chooseDistributionBaseline: baseline, acknowledgeDistributionAlert: ack }))
const releases: Array<() => void> = []
const policy: DistributionPolicy = { config_id: 'real-config', policy_id: 'policy-1', policy_version: 1,
  warning_threshold: 1.1, critical_threshold: 2.5, min_valid_count: 10, max_age_seconds: 600,
  created_at: '2026-10-20T00:00:00Z', resolution: 'next_valid_stable' }
const row: DriftObservation = { event_id: 'real-event', config_id: 'real-config', node_id: 'silo-01',
  model_name: 'ridge-model', version: '2.1.0', feature: 'x', state: 'ready', reason: '실제 공통 분포 비교',
  psi: 1.2, severity: 'warning', policy, baseline_id: 'baseline-1', baseline_report_id: 'baseline-report',
  current_report_id: 'current-report', baseline_at: '2026-10-20T00:00:00Z', current_at: '2026-10-20T00:10:00Z',
  window_start: '2026-10-20T00:10:00Z', window_end: '2026-10-20T00:11:00Z',
  baseline_window_start: '2026-10-20T00:00:00Z', baseline_window_end: '2026-10-20T00:01:00Z',
  baseline_total_count: 101, baseline_valid_count: 100, baseline_excluded_count: 1,
  current_total_count: 203, current_valid_count: 200, current_excluded_count: 3,
  bin_edges: [0, 10, 20], baseline_bin_counts: [50, 50], current_bin_counts: [10, 190],
  evaluated_at: '2026-10-20T00:10:00Z', basis_revision: 2 }
const alert: DistributionAlert = { alert_id: 'real-alert', event_id: row.event_id, config_id: row.config_id,
  node_id: row.node_id, model_name: row.model_name, version: row.version, feature: row.feature,
  policy_id: policy.policy_id, policy_version: 1, severity: 'warning', cause: 'ready', psi: 1.2,
  message: '실제 PSI 임계 초과', status: 'open', triggered_at: row.evaluated_at, acked_at: null,
  resolved_at: null, resolved_by_event_id: null }
const snapshot = (): DistributionOverview => ({ configs: [{ config_id: row.config_id, model_name: row.model_name,
  version: row.version, node_ids: [row.node_id], feature: 'x', bin_edges: [0, 10, 20], window_seconds: 60 }],
  items: [row], alerts: [alert] })
const observe = () => { const release = store.getState().observeLive(); releases.push(release); return release }
const loaded = async () => { observe(); await vi.waitFor(() => expect(store.getState().pollPending).toBe(false)) }
const html = () => renderToStaticMarkup(<><LiveDriftCard /><LiveDriftSettings /></>)
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (reason: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

beforeEach(() => {
  vi.clearAllMocks()
  useSimulationStore.setState({ mockEnabled: false, monitorPoints: [{ round: 9, throughput: 999, latency: 1, drift: 0.9 }] })
  store.setState({ liveRows: [], liveAlerts: [], liveConfigs: [], selectedScope: null, policyDraft: emptyDriftDraft(),
    draftDirty: false, liveError: null, livePending: false, pollPending: false, observers: 0 })
  fetch.mockResolvedValue(snapshot()); save.mockResolvedValue({}); baseline.mockResolvedValue({}); ack.mockResolvedValue({})
})
afterEach(() => { releases.splice(0).forEach((release) => release()); vi.restoreAllMocks() })

test('실제 PSI·N·버전·창·계보를 표시하고 데모의 90%를 대신 쓰지 않는다', async () => {
  await loaded()
  const content = html()
  for (const value of ['1.200000', 'ridge-model@2.1.0', 'silo-01', '기준 N 101', '현재 N 203',
    '2026-10-20T00:11:00Z', 'baseline-report', 'current-report', '실제 PSI 임계 초과']) expect(content).toContain(value)
  expect(content).not.toContain('90.0%')
  expect(content).toContain('백분율이 아닙니다')
})

test.each(['missing_baseline', 'stale', 'invalid', 'insufficient'] as const)('%s를 정상 PSI0으로 표시하지 않는다', async (state) => {
  fetch.mockResolvedValue({ ...snapshot(), items: [{ ...row, state, psi: null, severity: null }] })
  await loaded()
  const content = html()
  expect(content).toContain('계산할 수 없음')
  expect(content).not.toContain('0.000000')
  expect(content).not.toContain('<strong>정상</strong>')
})

test('빈 실제 응답은 데모나 정상값으로 채우지 않는다', async () => {
  fetch.mockResolvedValue({ configs: [], items: [], alerts: [] })
  await loaded()
  expect(html()).toContain('아직 정상 여부를 판단할 수 없습니다')
  expect(html()).not.toContain('1.200000')
})

test('poll 실패는 이전 snapshot과 갱신 실패를 함께 보존한다', async () => {
  await loaded(); fetch.mockRejectedValue(new Error('HTTP 503'))
  expect(await store.getState().pollLive()).toBe(false)
  expect(store.getState().liveRows).toEqual([row])
  expect(html()).toContain('HTTP 503')
  expect(html()).toContain('마지막 성공 조회값')
  expect(html()).toContain('현재 판단 불가')
  expect(html()).not.toContain('1.200000')
})

const stableSnapshot = (): DistributionOverview => ({ ...snapshot(), alerts: [], items: [{ ...row,
  psi: 0, severity: 'stable', current_bin_counts: [100, 100], reason: '실제 정상 비교' }] })
const requireUnavailable = () => {
  expect(html()).toContain('현재 판단 불가')
  expect(html()).toContain('계산할 수 없음')
  expect(html()).not.toContain('0.000000')
}

test.each(['policy', 'ack'] as const)('%s pending과 후속 GET pending은 실패한 snapshot을 정상 PSI0으로 복구하지 않는다', async (kind) => {
  fetch.mockResolvedValue(stableSnapshot()); await loaded()
  expect(html()).toContain('0.000000')
  fetch.mockRejectedValue(new Error('HTTP 503'))
  expect(await store.getState().pollLive()).toBe(false)
  requireUnavailable()
  const post = deferred<unknown>(), fresh = deferred<DistributionOverview>()
  if (kind === 'policy') save.mockReturnValue(post.promise)
  else ack.mockReturnValue(post.promise)
  fetch.mockReturnValue(fresh.promise)
  const action = kind === 'policy' ? store.getState().saveLivePolicy() : store.getState().ackLiveAlert(alert.alert_id)
  expect(store.getState()).toMatchObject({ livePending: true, liveError: 'HTTP 503' })
  requireUnavailable()
  post.resolve({})
  await vi.waitFor(() => expect(store.getState().pollPending).toBe(true))
  requireUnavailable()
  fresh.resolve(stableSnapshot())
  expect(await action).toBe(true)
  expect(store.getState().liveError).toBeNull()
  expect(html()).toContain('0.000000')
})

test.each([
  ['policy', 'post-fail'], ['policy', 'get-fail'], ['ack', 'post-fail'], ['ack', 'get-fail'],
] as const)('%s %s는 이전 조회 실패 뒤 정상 badge를 부활시키지 않는다', async (kind, failure) => {
  fetch.mockResolvedValue(stableSnapshot()); await loaded()
  fetch.mockRejectedValue(new Error('HTTP 503'))
  await store.getState().pollLive()
  const post = deferred<unknown>()
  if (kind === 'policy') save.mockReturnValue(post.promise)
  else ack.mockReturnValue(post.promise)
  const action = kind === 'policy' ? store.getState().saveLivePolicy() : store.getState().ackLiveAlert(alert.alert_id)
  requireUnavailable()
  if (failure === 'post-fail') post.reject(new Error('HTTP 409'))
  else post.resolve({})
  expect(await action).toBe(false)
  expect(store.getState().liveError).toBe(failure === 'post-fail' ? 'HTTP 409' : 'HTTP 503')
  requireUnavailable()
  fetch.mockResolvedValue(stableSnapshot())
  expect(await store.getState().pollLive()).toBe(true)
  expect(html()).toContain('0.000000')
})

test('서버 정책을 저장하고 재조회하며 편집 중 draft는 주기 poll이 덮지 않는다', async () => {
  await loaded()
  store.getState().setPolicyDraft('warning', '3.1')
  store.getState().setPolicyDraft('critical', '4.7')
  await store.getState().pollLive()
  expect(store.getState().policyDraft.warning).toBe('3.1')
  const saved = { ...policy, policy_version: 2, warning_threshold: 3.1, critical_threshold: 4.7 }
  fetch.mockResolvedValue({ ...snapshot(), items: [{ ...row, policy: saved }] })
  expect(await store.getState().saveLivePolicy()).toBe(true)
  expect(save).toHaveBeenCalledWith({ config_id: row.config_id, warning_threshold: 3.1,
    critical_threshold: 4.7, min_valid_count: 10, max_age_seconds: 600 })
  expect(store.getState().policyDraft).toEqual(draftForPolicy(saved))
  expect(html()).toContain('v2')
})

test('실제 report ID로 기준을 선택하고 경고 확인을 해소로 오인하지 않는다', async () => {
  await loaded()
  expect(await store.getState().chooseLiveBaseline()).toBe(true)
  expect(baseline).toHaveBeenCalledWith('current-report')
  fetch.mockResolvedValue({ ...snapshot(), alerts: [{ ...alert, status: 'acked', acked_at: row.evaluated_at }] })
  expect(await store.getState().ackLiveAlert(alert.alert_id)).toBe(true)
  expect(ack).toHaveBeenCalledWith('real-alert')
  expect(html()).toContain('확인함')
  expect(html()).not.toContain('<strong>해소됨</strong>')
})

test('경고 확인으로 편집 중인 정책 draft를 유실하지 않는다', async () => {
  await loaded()
  store.getState().setPolicyDraft('warning', '3.1')
  await store.getState().ackLiveAlert(alert.alert_id)
  expect(store.getState()).toMatchObject({ draftDirty: true, policyDraft: { warning: '3.1' } })
})

test('중복 mutation을 거부하며 실패한 요청은 이전 snapshot을 성공으로 바꾸지 않는다', async () => {
  await loaded()
  const late = deferred<unknown>(); ack.mockReturnValue(late.promise)
  const action = store.getState().ackLiveAlert(alert.alert_id)
  expect(await store.getState().chooseLiveBaseline()).toBe(false)
  expect(baseline).not.toHaveBeenCalled()
  late.resolve({}); expect(await action).toBe(true)
  save.mockRejectedValue(new Error('HTTP 409'))
  expect(await store.getState().saveLivePolicy()).toBe(false)
  expect(store.getState()).toMatchObject({ liveRows: [row], livePending: false, liveError: 'HTTP 409' })
})

test('mock 전환 뒤 늦은 응답을 버리고 live 복귀 시 실제 서버를 다시 읽는다', async () => {
  await loaded()
  const late = deferred<unknown>(); ack.mockReturnValue(late.promise)
  const action = store.getState().ackLiveAlert(alert.alert_id)
  useSimulationStore.setState({ mockEnabled: true })
  late.resolve({}); expect(await action).toBe(false)
  expect(store.getState()).toMatchObject({ liveRows: [], liveAlerts: [], livePending: false, selectedScope: null })
  useSimulationStore.setState({ mockEnabled: false })
  await vi.waitFor(() => expect(store.getState().liveRows).toEqual([row]))
})

test('선택 변경과 unmount 뒤 늦은 poll은 다른 사일로의 snapshot을 덮지 않는다', async () => {
  const late = deferred<DistributionOverview>(); fetch.mockReturnValueOnce(late.promise)
  const release = observe(); release()
  const other = { ...row, node_id: 'silo-1', current_report_id: 'new-current' }
  fetch.mockResolvedValue({ ...snapshot(), items: [other] })
  await loaded()
  late.resolve(snapshot()); await late.promise; await Promise.resolve()
  expect(store.getState().selectedScope).toBe(driftScopeKey(other))
  expect(store.getState().liveRows).toEqual([other])
})

test('live 정책과 demo 임계값·자동 재학습 설정은 서로 덮어쓰지 않는다', async () => {
  store.setState({ warnThreshold: 42, alertThreshold: 67, autoRetrain: true })
  await loaded()
  expect(store.getState().policyDraft.warning).toBe('1.1')
  useSimulationStore.setState({ mockEnabled: true })
  expect(store.getState()).toMatchObject({ warnThreshold: 42, alertThreshold: 67, autoRetrain: true, liveRows: [] })
  expect(save).not.toHaveBeenCalled()
})
