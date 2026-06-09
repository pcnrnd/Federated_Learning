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
