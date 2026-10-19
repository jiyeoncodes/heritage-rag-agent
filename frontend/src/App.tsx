// src/App.tsx
// ------------------------------------------------------------
// 화면 전체를 조립하는 최상위 컴포넌트예요.
// 요청 상태를 "하나의 값(status)"으로 관리해요: idle → loading → success | error
// 이렇게 하면 "로딩 중인데 결과도 보이는" 같은 모순된 화면이 생기지 않아요.
//
// 질문 방식(mode)이 두 가지예요.
//   agent : POST /api/agent/ask  — AI가 도구를 골라 유산 + 실록을 찾아 답해요. (기본)
//   rag   : POST /api/ask        — 유산 설명만 한 번 검색해서 답해요.
// 결과(success)에는 어느 방식으로 받은 답인지(mode)를 함께 담아서, 화면이 알맞은 모양으로 그려져요.
// ------------------------------------------------------------
import { useEffect, useRef, useState } from 'react'
import { ApiError, askAgent, askQuestion, fetchHealth } from './api'
import AgentSourceList from './components/AgentSourceList'
import AgentSteps from './components/AgentSteps'
import ModeToggle, { type Mode } from './components/ModeToggle'
import QuestionForm from './components/QuestionForm'
import SourceList from './components/SourceList'
import { AGENT_EXAMPLES, RAG_EXAMPLES } from './examples'
import type { AgentResponse, AskResponse, HealthResponse } from './types'

type Status =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'success'; mode: 'agent'; data: AgentResponse }
  | { kind: 'success'; mode: 'rag'; data: AskResponse }
  | { kind: 'error'; message: string }

export default function App() {
  const [mode, setMode] = useState<Mode>('agent')
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
      // 어느 방식으로 물어봤는지 이 시점의 mode를 기억해 두고 결과에 붙여요.
      if (mode === 'agent') {
        const data = await askAgent(q, ctrl.signal)
        setStatus({ kind: 'success', mode: 'agent', data })
      } else {
        const data = await askQuestion(q, ctrl.signal)
        setStatus({ kind: 'success', mode: 'rag', data })
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      setStatus({ kind: 'error', message: e instanceof ApiError ? e.message : '알 수 없는 오류가 발생했어요.' })
    }
  }

  // 방식을 바꾸면 이전 결과를 지워요. (Agent 결과 위에 RAG 안내가 겹쳐 보이는 혼동 방지)
  function handleModeChange(next: Mode) {
    setMode(next)
    setStatus({ kind: 'idle' })
  }

  const healthText =
    health === null ? '서버 확인 중…' : health === 'down' ? '서버 연결 안 됨' : `연결됨 · 자료 ${health.chunk_count}건`

  return (
    <main className="container">
      <header className="header">
        <h1>궁궐·종묘 AI 해설</h1>
        <span className={`health ${health === 'down' ? 'bad' : health ? 'ok' : ''}`}>{healthText}</span>
      </header>
      <p className="muted">
        국가유산청의 궁궐·종묘·경희궁·조선왕릉 자료와 조선왕조실록 기사 요약을 근거로 답하고, 출처를 함께 보여줘요.
        자료에 없는 내용은 "확인할 수 없다"고 답해요.
      </p>

      <ModeToggle mode={mode} disabled={status.kind === 'loading'} onChange={handleModeChange} />

      <QuestionForm
        question={question}
        loading={status.kind === 'loading'}
        examples={mode === 'agent' ? AGENT_EXAMPLES : RAG_EXAMPLES}
        onChange={setQuestion}
        onSubmit={handleAsk}
      />

      {status.kind === 'loading' && (
        <div className="card muted" role="status">
          {mode === 'agent'
            ? 'Agent가 필요한 자료를 찾아보는 중이에요… 여러 번 검색해서 10~40초쯤 걸릴 수 있어요.'
            : '자료를 찾고 답변을 만드는 중이에요…'}
        </div>
      )}
      {status.kind === 'error' && <div className="card error" role="alert">{status.message}</div>}

      {status.kind === 'success' && status.mode === 'agent' && (
        <>
          <section className="card">
            <h2>답변</h2>
            <p className="answer">{status.data.answer}</p>
            <p className="muted small">답변 모델: {status.data.model}</p>
          </section>
          <AgentSteps data={status.data} />
          <AgentSourceList sources={status.data.sources} />
        </>
      )}

      {status.kind === 'success' && status.mode === 'rag' && (
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
