import { useState } from 'react'

/** 표·블록 목록 한 페이지의 항목 수 */
export const PAGE_SIZE = 10

export interface Paged<T> {
  items: T[]
  page: number
  pageCount: number
  total: number
  setPage: (page: number) => void
}

export function usePaged<T>(all: readonly T[], size = PAGE_SIZE): Paged<T> {
  const [page, setPage] = useState(0)
  const pageCount = Math.max(1, Math.ceil(all.length / size))
  // 항목이 줄어 현재 페이지가 사라지면 마지막 페이지를 보여 준다
  const current = Math.min(page, pageCount - 1)
  return { items: all.slice(current * size, (current + 1) * size), page: current, pageCount, total: all.length, setPage }
}

/** 11건 이상일 때만 이전/다음과 현재 위치를 표시한다 */
export function Pager({ paged, label }: { paged: Paged<unknown>; label: string }) {
  const { page, pageCount, total, setPage } = paged
  if (pageCount <= 1) return null
  return (
    <nav className="table-pager" aria-label={label}>
      <button type="button" className="model-action" disabled={page === 0} onClick={() => setPage(page - 1)}>
        <i className="fa-solid fa-chevron-left" /> 이전
      </button>
      <span className="table-pager-status">
        {page + 1} / {pageCount} · 전체 {total}건
      </span>
      <button type="button" className="model-action" disabled={page >= pageCount - 1} onClick={() => setPage(page + 1)}>
        다음 <i className="fa-solid fa-chevron-right" />
      </button>
    </nav>
  )
}
