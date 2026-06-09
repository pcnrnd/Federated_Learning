import { useSimulationStore } from '@/store/useSimulationStore'

/**
 * 다크/라이트 테마 전환 스위치.
 * `role="switch"` + `aria-checked`(라이트=true)로 스크린리더 접근성을 보장하고,
 * 실제 전환은 스토어의 `toggleTheme`이 `<html data-theme>`와 localStorage를 갱신한다.
 */
export function ThemeToggle() {
  const theme = useSimulationStore((s) => s.theme)
  const toggleTheme = useSimulationStore((s) => s.toggleTheme)
  const isLight = theme === 'light'
  const label = isLight ? '다크 모드로 전환' : '라이트 모드로 전환'

  return (
    <button
      type="button"
      className="theme-toggle"
      role="switch"
      aria-checked={isLight}
      aria-label={label}
      title={label}
      onClick={toggleTheme}
    >
      <span className="theme-toggle-track" aria-hidden="true">
        <span className="theme-toggle-icon sun">
          <i className="fa-solid fa-sun" />
        </span>
        <span className="theme-toggle-icon moon">
          <i className="fa-solid fa-moon" />
        </span>
        <span className="theme-toggle-thumb" />
      </span>
    </button>
  )
}
