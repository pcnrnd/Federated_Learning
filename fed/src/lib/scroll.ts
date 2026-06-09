/** 지정 id 요소로 부드럽게 스크롤. 상태 변경 후 레이아웃 반영을 위해 다음 프레임에 실행. */
export function scrollToElement(id: string): void {
  window.requestAnimationFrame(() => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}
