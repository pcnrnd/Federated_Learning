import { expect, test } from 'vitest'
import { apiErrorMessage } from '@/api/client'

test('오류 문구에는 HTTP 코드·경로·JSON 원문이 들어가지 않는다', () => {
  expect(apiErrorMessage('/api/packaging/build', 409, '{"detail":"실제 가중치 파일이 없거나 비어 있습니다"}'))
    .toBe('모델 가중치 파일이 없어 패키징할 수 없습니다')
  expect(apiErrorMessage('/api/models', 409, '{"detail":"이미지 빌드 중인 모델 버전입니다"}')).toBe('이미지 빌드 중인 모델 버전입니다')
  expect(apiErrorMessage('/api/models', 401, '{"detail":"API key required"}')).toBe('권한이 없어 요청을 처리할 수 없습니다')
  expect(apiErrorMessage('/api/deployments', 422, '{"detail":[{"loc":["body","env"],"msg":"Field required"}]}'))
    .toBe('입력값을 확인한 뒤 다시 시도하세요')
  expect(apiErrorMessage('/api/deployments', 422, JSON.stringify({ detail: [{ loc: ['body', 'env'],
    msg: 'Value error, 환경변수 이름을 확인하세요', input: { SECRET: 'private-value' } }] }))).toBe('환경변수 이름을 확인하세요')
  expect(apiErrorMessage('/api/x', 500, '<html>Internal</html>')).toBe('서버 처리 중 문제가 발생했습니다. 잠시 후 다시 시도하세요')
  for (const status of [400, 401, 404, 409, 500]) {
    expect(apiErrorMessage('/api/silos', status, '')).not.toMatch(/HTTP|\/api\/|\{/)
  }
})
