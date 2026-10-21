import '@/test/currentSnapshotSsr'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

beforeEach(() => {
  vi.resetModules()
  vi.stubEnv('VITE_API_BASE', 'http://central')
})
afterEach(() => {
  vi.unstubAllEnvs()
})

test('라이브 JobScheduler는 데모와 같은 테이블 골격을 유지한다', async () => {
  const { useSimulationStore } = await import('@/store/useSimulationStore')
  useSimulationStore.setState({ mockEnabled: false })
  const { JobScheduler } = await import('@/components/data/JobScheduler')
  const html = renderToStaticMarkup(<JobScheduler />)
  expect(html).toContain('작업명')
  expect(html).toContain('파이프라인 등록')
})

test('미설정 API에서도 ControlPanel·NewModelForm 공통 카드가 유지된다', async () => {
  vi.stubEnv('VITE_API_BASE', '')
  const { useSimulationStore } = await import('@/store/useSimulationStore')
  useSimulationStore.setState({ mockEnabled: false })
  const { ControlPanel } = await import('@/components/controls/ControlPanel')
  const { NewModelForm } = await import('@/components/models/NewModelForm')
  expect(renderToStaticMarkup(<ControlPanel />)).toContain('시뮬레이션 구성 및 제어')
  expect(renderToStaticMarkup(<NewModelForm defaultProject="p" onClose={() => {}} />)).toContain('VITE_API_BASE')
})

test('라이브 NodeCard 어댑터는 CPU 미수집을 대시로 렌더한다', async () => {
  const { silosToDisplayNodes } = await import('@/lib/displayNodes')
  const { NodeCard } = await import('@/components/nodes/NodeCard')
  const node = silosToDisplayNodes(
    [{ id: 2, name: 'S2', endpoint: 'x', collectIntervalSec: 1, cpu: null, mem: null, disk: null, thresholds: { cpu: 1, mem: 1, disk: 1 } }],
    {},
  )[0]
  const html = renderToStaticMarkup(<NodeCard node={node} interactive={false} allNodes={[node]} />)
  expect(html).toContain('progress-text')
  expect(html).toContain('— (미수집)')
})
