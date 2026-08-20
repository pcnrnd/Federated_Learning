import { useEffect, useRef, useState } from 'react'
import { ThemeToggle } from './ThemeToggle'

/**
 * 사이드바 하단 설정 메뉴.
 * 상시 노출할 필요가 없는 표시 설정(테마 등)을 톱니 아이콘 뒤에 숨긴다.
 * 바깥 클릭·Esc로 닫히며, 열림 상태는 이 컴포넌트 안에서만 관리한다.
 */
export function SettingsMenu() {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return

    const onPointerDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }

    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  return (
    <div className="settings-menu" ref={rootRef}>
      <button
        type="button"
        className={`settings-trigger${open ? ' open' : ''}`}
        aria-expanded={open}
        aria-haspopup="true"
        aria-label="설정"
        title="설정"
        onClick={() => setOpen((v) => !v)}
      >
        <i className="fa-solid fa-gear" />
      </button>

      {open && (
        <div className="settings-popover glass-panel" role="menu">
          <span className="settings-popover-title">화면 설정</span>
          <div className="settings-row">
            <span className="settings-row-label">다크 모드</span>
            <ThemeToggle />
          </div>
        </div>
      )}
    </div>
  )
}
