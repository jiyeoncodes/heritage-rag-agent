// src/components/AgentSourceList.tsx
// ------------------------------------------------------------
// Agent가 찾아온 근거 자료 목록. 두 종류가 섞여 있어요.
//   - 유산 설명(heritage): 궁·왕릉 설명글. 이미지가 있으면 함께 보여줘요.
//   - 실록 기사(sillok)  : 조선왕조실록 기사의 AI 한글 요약 + 원문 링크.
// cited=true(답변 본문에 실제로 쓰인 자료)는 크게, 나머지는 접어서 보여줘요.
// ------------------------------------------------------------
import { useState } from 'react'
import type { AgentSource } from '../types'

// 원문 링크는 http/https 주소만 허용해요. (DB 값이 'javascript:...' 같은 위험한 주소여도 링크로 만들지 않으려는 안전장치)
function safeUrl(url: string | null): string | null {
  if (!url) return null
  try {
    const u = new URL(url)
    return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : null
  } catch {
    return null
  }
}

function SourceItem({ source }: { source: AgentSource }) {
  const [imgFailed, setImgFailed] = useState(false)

  if (source.kind === 'sillok') {
    const link = safeUrl(source.url)
    // label은 "날짜 제목" 형식이라, 앞쪽 날짜를 떼고 제목만 크게 보여줘요.
    const title = source.label.startsWith(source.date) ? source.label.slice(source.date.length).trim() : source.label
    return (
      <li className="source">
        <div>
          <div className="source-title">
            <span className="tag sillok">실록</span>
            <strong>{source.date}</strong>
            {source.tomb && <span className="tag">{source.tomb}</span>}
            <span className="sim">유사도 {source.similarity.toFixed(3)}</span>
          </div>
          {title && <p className="excerpt strong">{title}</p>}
          <p className="excerpt">{source.summary}</p>
          {link && (
            <a className="small" href={link} target="_blank" rel="noopener noreferrer">원문 보기 ↗</a>
          )}
        </div>
      </li>
    )
  }

  return (
    <li className="source">
      {source.img_url && !imgFailed && (
        <img src={source.img_url} alt={source.label} loading="lazy" onError={() => setImgFailed(true)} />
      )}
      <div>
        <div className="source-title">
          <span className="tag heritage">유산</span>
          <strong>{source.label}</strong>
          <span className="sim">유사도 {source.similarity.toFixed(3)}</span>
        </div>
        <p className="excerpt">{source.text}</p>
      </div>
    </li>
  )
}

// 같은 자료가 두 번 나와도 React가 헷갈리지 않게 종류+이름+순번으로 key를 만들어요.
const keyOf = (s: AgentSource, i: number) => `${s.kind}-${s.label}-${i}`

export default function AgentSourceList({ sources }: { sources: AgentSource[] }) {
  const cited = sources.filter((s) => s.cited)
  const others = sources.filter((s) => !s.cited)
  return (
    <section className="card">
      <h2>근거 자료</h2>
      {cited.length > 0 ? (
        <ul className="sources">{cited.map((s, i) => <SourceItem key={keyOf(s, i)} source={s} />)}</ul>
      ) : (
        <p className="muted">답변에 근거로 쓰인 자료가 없어요.</p>
      )}
      {others.length > 0 && (
        <details>
          <summary>Agent가 찾았지만 답변에 쓰지 않은 자료 {others.length}건 보기</summary>
          <ul className="sources">{others.map((s, i) => <SourceItem key={keyOf(s, i)} source={s} />)}</ul>
        </details>
      )}
    </section>
  )
}
