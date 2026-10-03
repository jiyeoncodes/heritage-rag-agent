// src/api.ts
// ------------------------------------------------------------
// 백엔드(FastAPI)와 대화하는 함수들을 모아 둔 파일이에요.
// 화면(컴포넌트)은 fetch의 세부 사항을 몰라도 askQuestion()만 부르면 돼요.
// ------------------------------------------------------------
import type { AskResponse, HealthResponse } from './types'

// 백엔드 주소: .env.local 의 VITE_API_BASE_URL 이 있으면 그것, 없으면 로컬 서버를 써요.
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '')

/** 사용자에게 그대로 보여줘도 되는 한글 오류 메시지를 담는 오류 클래스 */
export class ApiError extends Error {
  status: number | null // HTTP 상태 코드 (서버에 아예 못 닿았으면 null)
  constructor(message: string, status: number | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

// 서버가 보낸 오류 본문에서 사람이 읽을 메시지를 꺼내요.
// FastAPI는 오류를 {"detail": "문자열"} 또는 (입력 검증 실패 시) {"detail": [{msg: ...}]} 로 보내요.
async function readErrorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json()
    const detail = body?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail.length > 0 && typeof detail[0]?.msg === 'string') {
      return detail[0].msg
    }
  } catch {
    // JSON이 아닌 응답이면 아래 기본 메시지를 써요.
  }
  return `서버 오류가 발생했어요. (코드 ${res.status})`
}

// fetch 공통 처리: 네트워크 실패/중단/HTTP 오류를 ApiError로 통일해요.
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}${path}`, init)
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e // 사용자가 취소한 경우는 그대로 전달
    throw new ApiError('백엔드 서버에 연결할 수 없어요. 서버(uvicorn)가 켜져 있는지 확인해 주세요.')
  }
  if (!res.ok) throw new ApiError(await readErrorMessage(res), res.status)
  return (await res.json()) as T
}

/** 질문을 보내고 답변 + 출처를 받아와요. */
export function askQuestion(question: string, signal?: AbortSignal): Promise<AskResponse> {
  return request<AskResponse>('/api/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
    signal,
  })
}

/** 서버 상태(연결 여부, 저장된 자료 개수)를 확인해요. */
export function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return request<HealthResponse>('/api/health', { signal })
}
