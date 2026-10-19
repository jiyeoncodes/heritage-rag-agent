// src/components/ModeToggle.tsx
// ------------------------------------------------------------
// 질문 방식을 고르는 스위치: "Agent" ↔ "기본 RAG".
//  - Agent  : AI가 유산 검색 / 실록 검색 / 능 이름 찾기 중 필요한 도구를 직접 골라 여러 번 찾아봐요. (더 느리지만 폭넓게 답해요)
//  - 기본 RAG: 항상 유산 설명만 한 번 검색해서 답해요. (빠르지만 실록은 못 봐요)
// ------------------------------------------------------------
export type Mode = 'agent' | 'rag'

interface Props {
  mode: Mode
  disabled: boolean                 // 답변 만드는 중에는 바꾸지 못하게 막아요
  onChange: (mode: Mode) => void
}

const OPTIONS: { value: Mode; label: string; hint: string }[] = [
  { value: 'agent', label: 'Agent', hint: '유산 설명 + 실록 기사를 AI가 직접 골라 찾아요 (10~40초)' },
  { value: 'rag', label: '기본 RAG', hint: '유산 설명만 한 번 검색해서 빠르게 답해요' },
]

export default function ModeToggle({ mode, disabled, onChange }: Props) {
  const current = OPTIONS.find((o) => o.value === mode)
  return (
    <div className="mode">
      <div className="mode-buttons" role="radiogroup" aria-label="질문 방식">
        {OPTIONS.map((o) => (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={mode === o.value}
            className={`mode-btn ${mode === o.value ? 'active' : ''}`}
            disabled={disabled}
            onClick={() => onChange(o.value)}
          >
            {o.label}
          </button>
        ))}
      </div>
      <span className="muted small">{current?.hint}</span>
    </div>
  )
}
