// src/components/AgentSteps.tsx
// ------------------------------------------------------------
// "Agent가 한 일" 패널. AI가 어떤 도구를, 어떤 검색어로, 몇 번 불렀는지 순서대로 보여줘요.
// → 답이 어떻게 나왔는지 눈으로 확인할 수 있어서, 잘못 답했을 때 원인을 찾기 쉬워요.
// 안전장치(guard / retried)가 개입했으면 그것도 함께 알려줘요.
// ------------------------------------------------------------
import type { AgentResponse, AgentStep } from '../types'

// 도구 이름(영어) → 화면에 보여줄 한글 이름
const TOOL_LABELS: Record<string, string> = {
  search_heritage: '유산 설명 검색',
  search_sillok: '실록 검색',
  find_tomb_names: '능 이름 확인',
}

// 인자 {query: "영릉 천장", tomb: "영릉(세종)"} → 사람이 읽기 쉬운 한 줄. 빈 값은 생략해요.
const ARG_LABELS: Record<string, string> = { query: '검색어', keyword: '검색어', tomb: '능', reign: '왕대' }

function describeArgs(args: AgentStep['args']): string {
  return Object.entries(args)
    .filter(([, v]) => v !== '' && v !== null && v !== undefined)
    .map(([k, v]) => `${ARG_LABELS[k] ?? k}: ${String(v)}`)
    .join(' · ')
}

export default function AgentSteps({ data }: { data: AgentResponse }) {
  const { steps, guard, retried } = data
  return (
    <section className="card">
      <h2>Agent가 한 일</h2>
      {steps.length === 0 ? (
        <p className="muted">도구를 쓰지 않고 답했어요.</p>
      ) : (
        <ol className="steps">
          {steps.map((s, i) => (
            <li key={i} className="step">
              <span className="tag">{TOOL_LABELS[s.tool] ?? s.tool}</span>
              <span className="step-args">{describeArgs(s.args)}</span>
              <span className={`sim ${s.n_results === 0 ? 'none' : ''}`}>{s.n_results}건</span>
            </li>
          ))}
        </ol>
      )}
      {(guard || retried) && (
        <ul className="notes">
          {guard === 'nudged' && <li>AI가 검색 없이 답하려 해서, 먼저 자료를 찾아보게 했어요.</li>}
          {guard === 'replaced' && <li>검색 없이 근거 없는 답을 하려 해서, 답을 "확인할 수 없음"으로 바꿨어요.</li>}
          {retried && <li>AI가 검색을 덜 하고 포기하려 해서, 다른 검색어로 한 번 더 찾아보게 했어요.</li>}
        </ul>
      )}
    </section>
  )
}
