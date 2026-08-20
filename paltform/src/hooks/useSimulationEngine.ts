import { useCallback, useEffect, useRef } from 'react'
import {
  ALGORITHM_LABEL,
  TIMINGS,
  TRAFFIC_PER_NODE_MB,
} from '@/constants/simulation'
import {
  aggregateHierarchy,
  computeNodeEpochMetrics,
  effectiveEnabledNodes,
} from '@/lib/aggregation'
import { pickRandomIds } from '@/lib/format'
import { useModelStore } from '@/store/useModelStore'
import { useMonitoringStore } from '@/store/useMonitoringStore'
import { useSimulationStore } from '@/store/useSimulationStore'

class AbortedError extends Error {
  constructor() {
    super('aborted')
    this.name = 'AbortedError'
  }
}

/**
 * Simulation engine driving round-by-round federated learning.
 * - Single source of truth: Zustand store.
 * - Cancellation: every async step checks a generation token. Reset/unmount
 *   bumps the token, abandoning all in-flight callbacks safely.
 */
export function useSimulationEngine(): {
  start: () => void
  pause: () => void
  reset: () => void
} {
  const generationRef = useRef(0)

  const isLive = useCallback((gen: number): boolean => {
    return gen === generationRef.current && !useSimulationStore.getState().isPaused
  }, [])

  const sleep = useCallback(
    (ms: number, gen: number): Promise<void> =>
      new Promise((resolve, reject) => {
        const handle = window.setTimeout(() => {
          if (!isLive(gen)) reject(new AbortedError())
          else resolve()
        }, ms)
        if (gen !== generationRef.current) {
          window.clearTimeout(handle)
          reject(new AbortedError())
        }
      }),
    [isLive],
  )

  const runRound = useCallback(
    async (gen: number): Promise<void> => {
      const store = useSimulationStore.getState()
      const { config } = store

      store.incrementRound()
      const roundNo = useSimulationStore.getState().currentRound

      /** 중앙 서버에 직결된 1단 사일로 — WAN 트래픽·브로드캐스트 로그의 기준 */
      const rootNodes = () =>
        useSimulationStore.getState().nodes.filter((n) => n.parentId === undefined)
      /** HFL 하위 노드 — 하나도 없으면 엣지 페이즈 전체가 스킵된다 */
      const childNodes = () =>
        useSimulationStore.getState().nodes.filter((n) => n.parentId !== undefined)

      store.log(
        'server',
        `[ROUND ${roundNo}] 글로벌 가중치 파라미터 ${rootNodes().length}개 사일로로 브로드캐스트 전송...`,
      )

      // Phase 1: Download (server -> 1단 사일로)
      store.setPacketDirection('download')
      store.setAllNodeStatus('syncing')
      await sleep(TIMINGS.downloadAnimationMs, gen)
      if (!isLive(gen)) throw new AbortedError()
      store.setPacketDirection('idle')

      await sleep(TIMINGS.syncDelayMs, gen)
      if (!isLive(gen)) throw new AbortedError()
      store.log('server', '전 사일로 글로벌 매개변수 수신 및 복호화 완료.')

      // Phase 1b: Edge download (사일로 -> 하위 노드). 하위 노드가 없으면 스킵.
      const edgeChildren = childNodes()
      if (edgeChildren.length > 0) {
        store.setPacketDirection('edge-download')
        await sleep(TIMINGS.downloadAnimationMs, gen)
        if (!isLive(gen)) throw new AbortedError()
        store.setPacketDirection('idle')
        store.log(
          'server',
          `상위 사일로 → 하위 노드 ${edgeChildren.length}개 파라미터 배포 완료. (계층 연합 학습)`,
        )
      }

      // Phase 2: Local training
      store.setPacketDirection('local')
      store.setAllNodeStatus('training')
      store.setAllNodeCpu([80, 95])

      const totalEpochs = config.localEpochs
      store.log(
        'system',
        `전 사일로 로컬 데이터 연합 학습 시작 (반복: ${totalEpochs} Epochs, 속도: ${config.learningRate})`,
      )

      // 안내 로그 문구가 "사일로" 기준이므로 1단만 대상으로 뽑는다
      const announceIds = pickRandomIds(
        rootNodes().map((n) => n.id),
        3,
      )
      announceIds.forEach((id) => {
        const node = useSimulationStore.getState().nodes.find((n) => n.id === id)
        if (!node) return
        store.log(
          'client',
          `로컬 연계 프라이버시 데이터(${node.size.toLocaleString()}건) 최적화 연산 가속화 개시.`,
          id,
        )
      })

      const epochInterval = TIMINGS.trainingTotalMs / totalEpochs
      for (let epoch = 1; epoch <= totalEpochs; epoch++) {
        await sleep(epochInterval, gen)
        if (!isLive(gen)) throw new AbortedError()

        const progress = {
          currentRound: roundNo,
          totalRounds: config.totalRounds,
          epoch,
          totalEpochs,
        }
        effectiveEnabledNodes(useSimulationStore.getState().nodes).forEach((node) => {
          const next = computeNodeEpochMetrics(node, progress)
          store.updateNodeMetrics(node.id, next)
        })
      }
      store.log('system', '전 사일로 로컬 학습 완료. 로컬 가중치 업데이트 전송 준비.')

      // Phase 3a: Edge upload (하위 노드 -> 상위 사일로 로컬 집계). 하위가 없으면 스킵.
      const uploadingChildren = childNodes()
      if (uploadingChildren.length > 0) {
        const aggregatorIds = [...new Set(uploadingChildren.map((n) => n.parentId!))]
        store.setNodeStatusByIds(
          uploadingChildren.map((n) => n.id),
          'uploading',
        )
        store.setNodeStatusByIds(aggregatorIds, 'aggregating')
        store.setPacketDirection('edge-upload')
        await sleep(TIMINGS.downloadAnimationMs, gen)
        if (!isLive(gen)) throw new AbortedError()
        store.setPacketDirection('idle')

        // 애니메이션 대기 중 하위 노드가 해제됐을 수 있으므로 로그 직전에 다시 센다
        const settled = childNodes()
        aggregatorIds.forEach((parentId) => {
          const parent = rootNodes().find((n) => n.id === parentId)
          if (!parent) return
          const count = settled.filter((n) => n.parentId === parentId).length
          if (count === 0) return
          store.log('client', `[${parent.name}] 로컬 집계 완료 (하위 ${count}개)`, parentId)
        })
      }

      // Phase 3b: Upload (1단 사일로 -> 중앙 서버)
      store.setAllNodeStatus('uploading')
      store.setAllNodeCpu([3, 10])
      store.setPacketDirection('upload')
      await sleep(TIMINGS.downloadAnimationMs, gen)
      if (!isLive(gen)) throw new AbortedError()
      store.setPacketDirection('idle')

      // 하위→상위 전송은 사내망 취급이라 WAN 트래픽 집계에서 제외 — 1단 사일로 수만 과금
      const perNodeMB = TRAFFIC_PER_NODE_MB[config.algorithm]
      const roundTrafficMB = perNodeMB * rootNodes().length
      store.setGlobal({
        accumulatedTraffic:
          useSimulationStore.getState().global.accumulatedTraffic + roundTrafficMB,
      })

      const uploadAnnounceIds = pickRandomIds(
        rootNodes().map((n) => n.id),
        3,
      )
      uploadAnnounceIds.forEach((id) => {
        const node = useSimulationStore.getState().nodes.find((n) => n.id === id)
        if (!node) return
        store.log(
          'client',
          `로컬 파라미터 업데이트 암호화 전송 완료 (크기: ${perNodeMB.toFixed(2)} MB, 지연시간: ${node.delay} ms)`,
          id,
        )
      })
      store.log('server', '전 사일로 개별 연합 가중치 획득 성공. 통합 집계 단계 진입.')

      await sleep(TIMINGS.uploadDelayMs, gen)
      if (!isLive(gen)) throw new AbortedError()

      // Phase 4: Global aggregation
      store.setAllNodeStatus('idle')
      store.log('server', `[가중치 합산] ${ALGORITHM_LABEL[config.algorithm]} 연산 기동 중...`)

      await sleep(TIMINGS.aggregationMs, gen)
      if (!isLive(gen)) throw new AbortedError()

      const aggregated = aggregateHierarchy(
        useSimulationStore.getState().nodes,
        config.algorithm,
      )
      store.setGlobal({ accuracy: aggregated.accuracy, loss: aggregated.loss })

      if (config.algorithm === 'secagg') {
        store.log(
          'server',
          '[보안 암호화 해독] 가해식 난수화 마스킹 소거 완료. 글로벌 모델 가중치 병합 성공.',
        )
      }
      store.log(
        'success',
        `[ROUND ${roundNo} 완료] 글로벌 파라미터 업데이트 성공. (검증 정확도: ${aggregated.accuracy.toFixed(2)}%, 글로벌 Loss: ${aggregated.loss.toFixed(4)})`,
      )

      store.addChartPoint({
        round: roundNo,
        accuracy: aggregated.accuracy,
        loss: aggregated.loss,
      })

      // 모델 모니터링 지표(처리량/처리시간/드리프트) 갱신.
      // 정확도가 오를수록 처리량↑·처리시간↓, 드리프트는 라운드 누적으로 완만히 상승.
      const throughput = Math.round(110 + aggregated.accuracy * 1.8 + Math.random() * 15)
      const latency = Math.round(95 - aggregated.accuracy * 0.45 + Math.random() * 8)
      const drift = Math.min(1, Number((0.05 + roundNo * 0.025 + Math.random() * 0.03).toFixed(3)))
      store.addMonitorPoint({ round: roundNo, throughput, latency, drift })

      const monitoring = useMonitoringStore.getState()
      const alertThreshold = monitoring.alertThreshold / 100
      if (drift >= alertThreshold) {
        store.log(
          'error',
          `[모니터링] 데이터 드리프트 ${(drift * 100).toFixed(1)}% — 임계 초과! 재학습 검토 필요.`,
        )
        if (
          monitoring.autoRetrain &&
          monitoring.lastAutoRetrainRound !== roundNo &&
          monitoring.warnThreshold < monitoring.alertThreshold
        ) {
          const targetId =
            monitoring.retrainModelId === 'auto' ? undefined : monitoring.retrainModelId
          useModelStore.getState().triggerRetrain(targetId)
          useMonitoringStore.getState().setLastAutoRetrainRound(roundNo)
        }
      }

      await sleep(TIMINGS.betweenRoundsMs, gen)
      if (!isLive(gen)) throw new AbortedError()
    },
    [isLive, sleep],
  )

  const runLoop = useCallback(
    async (gen: number): Promise<void> => {
      try {
        while (isLive(gen)) {
          const { currentRound, config } = useSimulationStore.getState()
          if (currentRound >= config.totalRounds) {
            const { global } = useSimulationStore.getState()
            useSimulationStore
              .getState()
              .log(
                'success',
                `[학습 세션 완료] 총 ${config.totalRounds} 라운드 통합 연합 학습이 성공적으로 종료되었습니다.`,
              )
            useSimulationStore
              .getState()
              .log(
                'success',
                `최종 정확도: ${global.accuracy.toFixed(2)}%, 최저 글로벌 오차(Loss): ${global.loss.toFixed(4)}`,
              )
            useSimulationStore.setState({ isRunning: false })
            return
          }
          await runRound(gen)
        }
      } catch (err) {
        if (err instanceof AbortedError) return
        throw err
      }
    },
    [isLive, runRound],
  )

  const start = useCallback(() => {
    const store = useSimulationStore.getState()
    if (store.isRunning && !store.isPaused) return

    if (store.currentRound >= store.config.totalRounds) {
      store.reset()
    }

    const gen = ++generationRef.current
    store.startRunning()
    const { config } = useSimulationStore.getState()
    store.log(
      'system',
      `연합 오케스트레이터 기동 시작 (학습 구성 -> 알고리즘: ${ALGORITHM_LABEL[config.algorithm]}, 총 라운드: ${config.totalRounds})`,
    )
    void runLoop(gen)
  }, [runLoop])

  const pause = useCallback(() => {
    const store = useSimulationStore.getState()
    if (!store.isRunning || store.isPaused) return
    generationRef.current++ // abandon current generation
    store.pauseRunning()
    store.setAllNodeStatus('idle')
    store.setPacketDirection('idle')
    store.log('system', `오케스트레이터 일시정지 명령 수신 (현재 라운드: ${store.currentRound})`)
  }, [])

  const reset = useCallback(() => {
    generationRef.current++
    const store = useSimulationStore.getState()
    store.reset()
    store.log('system', '연합 학습 대시보드 리셋 완료. 새로운 오케스트레이션 세션 대기 중.')
  }, [])

  // Abandon any in-flight work when the component unmounts.
  useEffect(() => {
    return () => {
      generationRef.current++
    }
  }, [])

  return { start, pause, reset }
}

export type SimulationControls = ReturnType<typeof useSimulationEngine>

const noopControls: SimulationControls = {
  start: () => {},
  pause: () => {},
  reset: () => {},
}

let activeEngineControls: SimulationControls | null = null

/**
 * 앱 루트에 마운트해 탭 전환과 무관하게 시뮬레이션 루프를 유지한다.
 */
export function SimulationEngineHost(): null {
  const controls = useSimulationEngine()

  useEffect(() => {
    activeEngineControls = controls
    return () => {
      activeEngineControls = null
    }
  }, [controls])

  return null
}

/** ControlPanel 등 자식 컴포넌트에서 엔진 제어 함수를 참조한다. */
export function getSimulationControls(): SimulationControls {
  return activeEngineControls ?? noopControls
}
