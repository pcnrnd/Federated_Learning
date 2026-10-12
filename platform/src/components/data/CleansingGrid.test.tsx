import { describe, expect, test } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { CleansingGrid } from '@/components/data/CleansingGrid'
import type { SiloData } from '@/types/simulation'

/** HVC 정제 샤드가 보고하는 것과 같은 `<step>.<항목>[.<세부>]` 키 묶음 (실측 순서 그대로) */
const HVC_COUNTERS: Record<string, number> = {
  'MAP_SCHEMA.CAST_FAILED': 4,
  MAP_SCHEMA: 639,
  'MAP_SCHEMA.ROWS.PERIOD_A': 189,
  'MAP_SCHEMA.ROWS.PERIOD_B': 150,
  'MAP_SCHEMA.ROWS.ENTITY': 300,
  'UNION_SOURCES.IN.PERIOD_A': 189,
  'UNION_SOURCES.DUPLICATES.WITHIN': 9,
  'UNION_SOURCES.DUPLICATES.CROSS': 30,
  'UNION_SOURCES.OUT': 300,
  'JOIN_SOURCES.EXCLUDED.LEFT_ONLY': 15,
  'JOIN_SOURCES.MATCHED': 285,
  'PARSE_RECORDS.IN': 429,
  'PARSE_RECORDS.CONVERSION_FAILED': 5,
  'PARSE_RECORDS.CONVERSION_FAILED.CAST_FAILED': 1,
  'PARSE_RECORDS.CONVERSION_FAILED.UNKNOWN_UNIT': 2,
  'PARSE_RECORDS.CONVERSION_FAILED.UNKNOWN_CODE': 2,
  'RECONCILE.CONFLICTS': 51,
  'RECONCILE.RESOLVED.PRIORITY': 11,
  'RECONCILE.RESOLVED.LATEST': 29,
  'RECONCILE.RESOLVED.TOLERANCE': 7,
  'RECONCILE.UNRESOLVED': 4,
  'VALIDATE_SCHEMA.EXCLUDED.MISSING': 32,
  'VALIDATE_SCHEMA.EXCLUDED.OUT_OF_RANGE': 6,
  'VALIDATE_SCHEMA.OUT': 1068,
}

const silo = (overrides: Partial<SiloData> = {}): SiloData => ({
  siloId: 1,
  name: 'silo-1',
  cleansePct: 100,
  shardCount: 1,
  records: 1068,
  cleanseStatus: 'completed',
  stepCounters: HVC_COUNTERS,
  ...overrides,
})

/** 렌더 결과에서 카운터 칩의 텍스트만 순서대로 뽑는다 (태그 제거) */
function counterChips(html: string): string[] {
  const block = html.match(/<div class="cleanse-counters"[^>]*>(.*?)<\/div>/)?.[1] ?? ''
  return block
    .split('<span class="cleanse-counter">')
    .slice(1)
    .map((chip) => chip.replace(/<[^>]+>/g, ''))
}

describe('CleansingGrid step counters', () => {
  test('renders every counter as its own chip, in the given order and with the same numbers', () => {
    const html = renderToStaticMarkup(<CleansingGrid siloData={[silo()]} />)
    const chips = counterChips(html)

    expect(chips).toEqual(
      Object.entries(HVC_COUNTERS).map(([step, n]) => `${step} ${n.toLocaleString('ko-KR')}`),
    )
    expect(chips).toHaveLength(24)
    expect(chips.at(-1)).toBe('VALIDATE_SCHEMA.OUT 1,068')
  })

  test('counters live in a separate wrapping block, not inside the badge row', () => {
    const html = renderToStaticMarkup(<CleansingGrid siloData={[silo()]} />)

    const badgeRow = html.match(/<div class="cleanse-progress-row"><span class="dep-state-badge[^"]*">정제 완료<\/span><\/div>/)
    expect(badgeRow).not.toBeNull()
    expect(badgeRow![0]).not.toContain('cleanse-counter')

    const block = html.match(/<div class="cleanse-counters"[^>]*>/)
    expect(block).not.toBeNull()
    expect(html.indexOf('cleanse-counters')).toBeGreaterThan(html.indexOf('정제 완료'))
  })

  test('long dotted keys get a break opportunity after every "." so they cannot overflow the card', () => {
    const html = renderToStaticMarkup(<CleansingGrid siloData={[silo()]} />)

    expect(html).toContain(
      '<span>PARSE_RECORDS</span><span>.<wbr/>CONVERSION_FAILED</span><span>.<wbr/>UNKNOWN_UNIT</span> 2',
    )
    // 점이 없는 키는 그대로, <wbr> 없이
    expect(html).toContain('<span class="cleanse-counter"><span>MAP_SCHEMA</span> 639</span>')
  })

  test('no counter block when the shard has no counters or no live status', () => {
    const empty = renderToStaticMarkup(<CleansingGrid siloData={[silo({ stepCounters: {} })]} />)
    expect(empty).not.toContain('cleanse-counters')
    expect(empty).toContain('정제 완료')

    const noStatus = renderToStaticMarkup(
      <CleansingGrid siloData={[silo({ cleanseStatus: undefined })]} />,
    )
    expect(noStatus).not.toContain('cleanse-counters')
    expect(noStatus).not.toContain('dep-state-badge')
  })
})
