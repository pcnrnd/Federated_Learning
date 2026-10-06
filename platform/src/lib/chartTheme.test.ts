import { describe, expect, test } from 'vitest'
import { siloColorSlot, siloColorVar } from '@/lib/chartTheme'

describe('siloColorSlot', () => {
  test('maps silo-N to slot N and wraps after 8', () => {
    expect(siloColorSlot('silo-1')).toBe(1)
    expect(siloColorSlot('silo-6')).toBe(6)
    expect(siloColorSlot('silo-9')).toBe(1)
    expect(siloColorSlot('silo-0')).toBe(8)
  })

  test('gives a stable slot for ids without trailing digits', () => {
    const slot = siloColorSlot('hospital-A')
    expect(slot).toBeGreaterThanOrEqual(1)
    expect(slot).toBeLessThanOrEqual(8)
    expect(siloColorSlot('hospital-A')).toBe(slot)
  })

  test('exposes the slot as a CSS variable reference', () => {
    expect(siloColorVar('silo-3')).toBe('var(--silo-3)')
  })
})
