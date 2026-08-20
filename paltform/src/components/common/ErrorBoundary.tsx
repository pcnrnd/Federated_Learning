import { Component, type ErrorInfo, type ReactNode } from 'react'

interface ErrorBoundaryProps {
  children: ReactNode
  /** 경계 식별용 라벨(예: 활성 탭). 변경되면 에러 상태를 자동 리셋한다. */
  resetKey?: string
}

interface ErrorBoundaryState {
  error: Error | null
}

/**
 * 하위 트리의 렌더 에러를 포착해 앱 전체가 빈 화면이 되는 것을 막는다.
 * React 에러 경계는 클래스 컴포넌트로만 구현 가능하다.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidUpdate(prevProps: ErrorBoundaryProps): void {
    // 탭 전환 등 resetKey 변경 시 에러 상태를 해제해 정상 화면으로 복귀
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null })
    }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('[ErrorBoundary] 렌더 중 오류가 발생했습니다.', error, info)
  }

  private handleRetry = (): void => {
    this.setState({ error: null })
  }

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div className="tab-pane">
        <div className="glass-panel content-card full-card error-boundary-card">
          <div className="error-boundary-body">
            <i className="fa-solid fa-triangle-exclamation error-boundary-icon" />
            <h3 className="error-boundary-title">화면을 표시하는 중 오류가 발생했습니다.</h3>
            <p className="error-boundary-desc">
              이 영역만 일시적으로 중단되었으며, 다른 탭은 정상적으로 사용할 수 있습니다.
            </p>
            <pre className="error-boundary-detail">{error.message}</pre>
            <button type="button" className="btn btn-primary error-boundary-retry" onClick={this.handleRetry}>
              <i className="fa-solid fa-arrows-rotate" /> 다시 시도
            </button>
          </div>
        </div>
      </div>
    )
  }
}
