import { NewModelForm } from './NewModelForm'

interface LiveModelFormProps {
  onClose: () => void
}

/** @deprecated 통합 NewModelForm을 사용한다. 기존 테스트·import 호환용 래퍼 */
export function LiveModelForm({ onClose }: LiveModelFormProps) {
  return <NewModelForm defaultProject="" onClose={onClose} />
}
