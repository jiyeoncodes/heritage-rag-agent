// src/components/QuestionForm.tsx
// ------------------------------------------------------------
// 질문 입력창 + 예시 질문 버튼 + 전송 버튼.
// "입력값(question)"은 부모(App)가 들고 있고, 이 컴포넌트는 받은 값을 보여주기만 해요.
// (이런 방식을 '상태 끌어올리기'라고 해요.)
// ------------------------------------------------------------
import type { FormEvent } from 'react'

const MAX_LENGTH = 300 // 백엔드 AskRequest 의 max_length 와 같아야 해요.

interface Props {
  question: string
  loading: boolean
  examples: string[]        // 예시 질문 버튼에 보여줄 문장들 (모드마다 달라요: src/examples.ts)
  onChange: (value: string) => void
  onSubmit: (question: string) => void
}

export default function QuestionForm({ question, loading, examples, onChange, onSubmit }: Props) {
  const trimmed = question.trim()
  const canSubmit = trimmed.length > 0 && !loading

  function handleSubmit(e: FormEvent) {
    e.preventDefault() // 폼 기본 동작(페이지 새로고침) 막기
    if (canSubmit) onSubmit(trimmed)
  }

  return (
    <form className="card" onSubmit={handleSubmit}>
      <label htmlFor="question" className="label">궁궐·종묘에 대해 궁금한 점을 물어보세요</label>
      <textarea
        id="question"
        value={question}
        maxLength={MAX_LENGTH}
        rows={3}
        placeholder={`예) ${examples[0] ?? ''}`}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          // Enter = 전송, Shift+Enter = 줄바꿈. (한글 조합 중 Enter는 무시해야 해서 isComposing 확인)
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault()
            if (canSubmit) onSubmit(trimmed)
          }
        }}
      />
      <div className="row">
        <span className="counter">{question.length} / {MAX_LENGTH}</span>
        <button type="submit" disabled={!canSubmit}>{loading ? '답변 만드는 중…' : '질문하기'}</button>
      </div>
      <div className="chips" aria-label="예시 질문">
        {examples.map((ex) => (
          <button key={ex} type="button" className="chip" disabled={loading} onClick={() => onChange(ex)}>
            {ex}
          </button>
        ))}
      </div>
    </form>
  )
}
