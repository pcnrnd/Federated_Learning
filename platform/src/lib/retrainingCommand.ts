export interface PendingRetrainingCommand { configId: string; requestId: string; acceptedEventId?: string }
const storageKey = () => `fed-retraining-command:${import.meta.env.VITE_API_BASE ?? ''}`

/** 새로고침도 미확인 실서버 명령을 새 의도로 바꾸지 않는다. 원시 데이터는 저장하지 않는다. */
export function readRetrainingCommand(): PendingRetrainingCommand | null {
  try {
    const value = JSON.parse(window.localStorage.getItem(storageKey()) ?? 'null') as PendingRetrainingCommand | null
    if (value && typeof value.configId === 'string' && typeof value.requestId === 'string'
      && (value.acceptedEventId === undefined || typeof value.acceptedEventId === 'string')) {
      return { configId: value.configId, requestId: value.requestId, ...(value.acceptedEventId ? { acceptedEventId: value.acceptedEventId } : {}) }
    }
  } catch { /* 저장소 접근 실패는 현재 세션의 명령 보존을 막지 않는다. */ }
  return null
}
export function persistRetrainingCommand(command: PendingRetrainingCommand | null): void {
  try {
    if (command) window.localStorage.setItem(storageKey(), JSON.stringify(command))
    else window.localStorage.removeItem(storageKey())
  } catch { /* 저장 불가 시에도 현재 세션에서는 동일 ID를 재사용한다. */ }
}
