export function nowTimestamp(): string {
  return new Date().toLocaleTimeString('ko-KR', { hour12: false })
}

export function formatPercent(value: number, digits = 2): string {
  return `${value.toFixed(digits)}%`
}

export function formatMB(value: number, digits = 2): string {
  return `${value.toFixed(digits)} MB`
}

export function formatNumber(value: number): string {
  return value.toLocaleString('ko-KR')
}

export function pickRandomIds(ids: readonly number[], count: number): number[] {
  const shuffled = [...ids].sort(() => Math.random() - 0.5)
  return shuffled.slice(0, Math.min(count, ids.length))
}
