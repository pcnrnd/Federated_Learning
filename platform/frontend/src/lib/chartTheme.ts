/**
 * Chart.js 색상을 현재 테마(`<html data-theme>`)의 CSS 토큰에서 해석한다.
 * Chart.js 옵션은 순수 색상 문자열을 요구하므로 CSS 변수를 직접 넘길 수 없다 —
 * 렌더 시점에 계산값을 읽어 변환하고, 컴포넌트는 theme 의존 useMemo로 재계산해
 * 테마 전환에 반응한다.
 */
export interface ChartTheme {
  /** 축 라벨·범례·타이틀 텍스트 */
  text: string
  /** 그리드 라인 */
  grid: string
  tooltipBg: string
  tooltipTitle: string
  tooltipBody: string
  tooltipBorder: string
}

function cssVar(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

export function getChartTheme(): ChartTheme {
  // --ink 채널(밝음/어둠 반전)을 이용해 테마에 맞는 반투명 그리드/보더를 만든다.
  const ink = cssVar('--ink', '255 255 255')
  return {
    text: cssVar('--text-secondary', '#9ca3af'),
    grid: `rgb(${ink} / 0.06)`,
    tooltipBg: cssVar('--surface-2', '#111827'),
    tooltipTitle: cssVar('--text-strong', '#ffffff'),
    tooltipBody: cssVar('--text-primary', '#e5e7eb'),
    tooltipBorder: `rgb(${ink} / 0.12)`,
  }
}

/** 사일로 고정색 슬롯 수 (`--silo-1` ~ `--silo-8`, global.css) */
export const SILO_COLOR_SLOTS = 8

/**
 * 사일로 id → 고정색 슬롯(1~8). 차트가 달라도 같은 사일로는 같은 색이다.
 * "silo-3" → 3. 끝자리 숫자가 없으면 문자 코드 합으로 고정한다.
 */
export function siloColorSlot(siloId: string): number {
  const match = /(\d+)\s*$/.exec(siloId)
  const n = match
    ? Number(match[1]) - 1
    : [...siloId].reduce((sum, ch) => sum + ch.charCodeAt(0), 0)
  return (((n % SILO_COLOR_SLOTS) + SILO_COLOR_SLOTS) % SILO_COLOR_SLOTS) + 1
}

/** SVG·HTML용 — CSS 변수 참조라 테마 전환을 자동으로 따른다 */
export function siloColorVar(siloId: string): string {
  return `var(--silo-${siloColorSlot(siloId)})`
}

/** Chart.js용 — 렌더 시점의 계산값 (theme 의존 useMemo에서 호출) */
export function siloColor(siloId: string): string {
  return cssVar(`--silo-${siloColorSlot(siloId)}`, '#6366f1')
}

/** 단일 계열 차트 색 (강조 토큰 그대로) */
export function accentColor(name: 'primary' | 'cyan' | 'green'): string {
  return cssVar(`--${name}`, '#6366f1')
}

/** 시각화 탭 공통 툴팁 */
export function vizTooltip(t: ChartTheme) {
  return {
    backgroundColor: t.tooltipBg,
    titleColor: t.tooltipTitle,
    bodyColor: t.tooltipBody,
    borderColor: t.tooltipBorder,
    borderWidth: 1,
  }
}

/**
 * 시각화 탭 공통 축 — 단일 y축, 그리드는 y만 옅게.
 * 막대는 0 기준선이 필수, 선은 변화가 보이도록 `beginAtZero: false`로 자동 범위를 쓴다.
 */
export function vizAxes(
  t: ChartTheme,
  xTitle: string,
  yTitle: string,
  { max, beginAtZero = true }: { max?: number; beginAtZero?: boolean } = {},
) {
  const title = (text: string) => ({ display: true, text, color: t.text, font: { size: 11 } })
  return {
    x: { grid: { display: false }, ticks: { color: t.text, font: { size: 11 } }, title: title(xTitle) },
    y: {
      beginAtZero,
      ...(max !== undefined ? { max } : {}),
      grid: { color: t.grid },
      ticks: { color: t.text, font: { size: 11 } },
      title: title(yTitle),
    },
  }
}
