// src/App.tsx
// ------------------------------------------------------------
// 화면 전체를 조립하는 최상위 컴포넌트예요.
// 요청 상태를 "하나의 값(status)"으로 관리해요: idle → loading → success | error
// 이렇게 하면 "로딩 중인데 결과도 보이는" 같은 모순된 화면이 생기지 않아요.
// ------------------------------------------------------------
import { useEffect, useRef, useState } from 'react'
import { ApiError, askQuestion, fetchHealth } from './api'
import QuestionForm from './components/QuestionForm'
import SourceList from './components/SourceList'
import type { AskResponse, HealthResponse } from './types'

type Status =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'success'; data: AskResponse }
  | { kind: 'error'; message: string }

export default function App() {
  const [question, setQuestion] = useState('')
  const [status, setStatus] = useState<Status>({ kind: 'idle' })
  const [health, setHealth] = useState<HealthResponse | null | 'down'>(null) // null=확인 중
  const abortRef = useRef<AbortController | null>(null) // 진행 중 요청을 취소하기 위한 리모컨

  // 처음 화면이 뜰 때 서버 상태를 한 번 확인해요.
  useEffect(() => {
    const ctrl = new AbortController()
    fetchHealth(ctrl.signal)
      .then(setHealth)
      .catch((e) => {
        if (!(e instanceof DOMException && e.name === 'AbortError')) setHealth('down')
      })
    return () => ctrl.abort()
  }, [])

  async function handleAsk(q: string) {
    abortRef.current?.abort() // 이전 요청이 남아 있으면 취소
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setStatus({ kind: 'loading' })
    try {
      const data = await askQuestion(q, ctrl.signal)
      setStatus({ kind: 'success', data })
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      setStatus({ kind: 'error', message: e instanceof ApiError ? e.message : '알 수 없는 오류가 발생했어요.' })
    }
  }

  const healthText =
    health === null ? '서버 확인 중…' : health === 'down' ? '서버 연결 안 됨' : `연결됨 · 자료 ${health.chunk_count}건`

  return (
    <main className="container">
      <header className="header">
        <h1>궁궐·종묘 AI 해설</h1>
        <span className={`health ${health === 'down' ? 'bad' : health ? 'ok' : ''}`}>{healthText}</span>
      </header>
      <p className="muted">국가유산청의 궁궐·종묘·경희궁·조선왕릉 자료를 근거로 답하고, 출처를 함께 보여줘요. 자료에 없는 내용은 "확인할 수 없다"고 답해요.</p>

      <QuestionForm question={question} loading={status.kind === 'loading'} onChange={setQuestion} onSubmit={handleAsk} />

      {status.kind === 'loading' && <div className="card muted" role="status">자료를 찾고 답변을 만드는 중이에요…</div>}
      {status.kind === 'error' && <div className="card error" role="alert">{status.message}</div>}
      {status.kind === 'success' && (
        <>
          <section className="card">
            <h2>답변</h2>
            <p className="answer">{status.data.answer}</p>
            <p className="muted small">답변 모델: {status.data.model}</p>
          </section>
          <SourceList sources={status.data.sources} />
        </>
      )}
    </main>
  )
}
