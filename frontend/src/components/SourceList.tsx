// src/components/SourceList.tsx
// ------------------------------------------------------------
// 답변의 근거 자료 목록.
//  - cited=true  : AI가 답변 끝에 "출처"로 직접 적은 유산 → 크게 보여줘요.
//  - cited=false : 검색은 됐지만 출처로 적지 않은 후보 → 접어서(펼치기) 보여줘요.
// ------------------------------------------------------------
import { useState } from 'react'
import type { Source } from '../types'

function SourceItem({ source }: { source: Source }) {
  // 이미지 주소가 깨졌을 때 빈 칸 대신 이미지를 숨기기 위한 상태
  const [imgFailed, setImgFailed] = useState(false)
  return (
    <li className="source">
      {source.img_url && !imgFailed && (
        <img src={source.img_url} alt={`${source.gung_name} ${source.name}`} loading="lazy" onError={() => setImgFailed(true)} />
      )}
      <div>
        <div className="source-title">
          <strong>{source.name}</strong>
          <span className="tag">{source.gung_name}</span>
          <span className="sim">유사도 {source.similarity.toFixed(3)}</span>
        </div>
        <p className="excerpt">{source.excerpt}</p>
      </div>
    </li>
  )
}

export default function SourceList({ sources }: { sources: Source[] }) {
  const cited = sources.filter((s) => s.cited)
  const others = sources.filter((s) => !s.cited)
  return (
    <section className="card">
      <h2>참고한 자료</h2>
      {cited.length > 0 ? (
        <ul className="sources">{cited.map((s) => <SourceItem key={`${s.gung_name}-${s.name}`} source={s} />)}</ul>
      ) : (
        <p className="muted">AI가 출처로 직접 표시한 자료가 없어요.</p>
      )}
      {others.length > 0 && (
        <details>
          <summary>검색된 다른 후보 {others.length}건 보기</summary>
          <ul className="sources">{others.map((s) => <SourceItem key={`${s.gung_name}-${s.name}`} source={s} />)}</ul>
        </details>
      )}
    </section>
  )
}
