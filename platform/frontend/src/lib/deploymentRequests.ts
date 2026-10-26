import { parseModelKey } from '@/api/mappers'
import type { DeploymentRequestApi } from '@/api/client'
import type { DeployInput } from '@/store/useModelStore'
import type { Silo } from '@/types/simulation'

const RESERVED = new Set(['MODEL_NAME', 'MODEL_VERSION', 'MODEL_FRAMEWORK', 'MODEL_PATH', 'ARTIFACT_ROOT', 'MODEL_META_PATH'])

export function parseDeploymentEnv(text: string): Record<string, string> {
  const result: Record<string, string> = {}
  for (const line of text.split('\n').filter((value) => value.trim())) {
    const split = line.indexOf('=')
    const key = line.slice(0, split).trim()
    if (split < 1 || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(key) || RESERVED.has(key) || Object.hasOwn(result, key)) {
      throw new Error('환경변수는 중복·예약 이름 없이 KEY=value 형식으로 입력하세요')
    }
    const value = line.slice(split + 1)
    if (value.includes('\0')) throw new Error('환경변수에는 NUL을 사용할 수 없습니다')
    result[key] = value
  }
  return result
}

export function deploymentPayload(input: DeployInput, silos: readonly Silo[]): DeploymentRequestApi {
  const { name, version } = parseModelKey(input.modelId)
  const selected = input.targetSiloIds.length ? silos.filter((silo) => input.targetSiloIds.includes(silo.id)) : silos
  if (input.targetSiloIds.length && (selected.length !== input.targetSiloIds.length
      || new Set(input.targetSiloIds).size !== input.targetSiloIds.length)) {
    throw new Error('선택한 배포 대상이 현재 사일로 목록과 다릅니다')
  }
  const targets = selected.map((silo) => silo.serverId ?? silo.name)
  if (!targets.length || new Set(targets).size !== targets.length) throw new Error('정확한 배포 대상 사일로를 선택하세요')
  if (input.strategy === 'batch' && (!Number.isInteger(input.intervalSec) || (input.intervalSec ?? 0) < 1)) {
    throw new Error('일괄 배포 주기는 양의 정수 초로 입력하세요')
  }
  if (input.inferencePort !== undefined && (!Number.isInteger(input.inferencePort) || input.inferencePort < 1 || input.inferencePort > 65535)) {
    throw new Error('컨테이너 내부 포트는 1~65535의 정수로 입력하세요')
  }
  return { model_name: name, version, strategy: input.strategy, target_node_ids: targets,
    env: input.env ?? {}, ...(input.strategy === 'batch' ? { interval_seconds: input.intervalSec } : {}),
    ...(input.inferencePort !== undefined ? { inference_port: input.inferencePort } : {}),
    ...(input.probeInputs ? { probe_inputs: input.probeInputs } : {}) }
}

export function newDeploymentRequestId(): string {
  return Array.from(crypto.getRandomValues(new Uint32Array(4)), (value) => value.toString(16).padStart(8, '0')).join('')
}
