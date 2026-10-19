// src/types.ts
// ------------------------------------------------------------
// 백엔드(backend/main.py)가 돌려주는 JSON의 "모양"을 TypeScript 타입으로 적어 둔 파일이에요.
// 이렇게 해 두면, 화면 코드에서 존재하지 않는 항목(예: source.nmae)을 쓰는 실수를
// 코드를 실행하기 전에 에디터가 바로 빨간 줄로 알려줘요.
// ⚠ 백엔드의 pydantic 모델(Source, AskResponse)과 항상 같은 모양이어야 해요.
// ------------------------------------------------------------

/** 답변에 참고한 자료(유산) 한 건 */
export interface Source {
  gung_name: string       // 궁 이름 (예: 경복궁)
  name: string            // 유산 이름 (예: 광화문)
  similarity: number      // 질문과의 유사도 (1에 가까울수록 비슷)
  img_url: string | null  // 대표 이미지 주소 (없으면 null)
  excerpt: string         // 참고한 설명글의 앞부분 미리보기
  cited: boolean          // AI가 답변의 출처로 직접 적은 유산이면 true
}

/** POST /api/ask 의 응답 */
export interface AskResponse {
  answer: string          // AI 답변 (출처 줄은 sources에 따로 있어요)
  model: string           // 실제로 답한 AI 모델 이름
  sources: Source[]       // 검색된 참고 자료 목록 (유사도 높은 순)
}

/** GET /api/health 의 응답 */
export interface HealthResponse {
  status: string
  chunk_count: number     // DB에 저장된 유산 개수
  llm_model: string
  fallback_model: string
  embedding_model: string
}

// ------------------------------------------------------------
// Agent (POST /api/agent/ask) 응답 타입
// ⚠ 백엔드 main.py 의 AgentStep, AgentResponse 와 같은 모양이어야 해요.
// ------------------------------------------------------------

/** Agent가 부른 도구 한 번의 기록 */
export interface AgentStep {
  tool: string                     // 도구 이름 (search_heritage / search_sillok / find_tomb_names)
  args: Record<string, unknown>    // 도구에 넘긴 인자 (예: { query: "영릉 천장" })
  n_results: number                // 도구가 찾아온 자료 수
}

/** Agent가 찾아온 자료의 공통 부분 */
interface AgentSourceBase {
  label: string                    // 출처 표시용 이름 (예: "경복궁 광화문", "세종실록 28년 7월 20일 …")
  similarity: number               // 질문과의 유사도
  cited: boolean                   // 답변 본문에 실제로 쓰였으면 true
}

/** 유산 설명 자료 (kind === 'heritage') */
export interface HeritageAgentSource extends AgentSourceBase {
  kind: 'heritage'
  text: string                     // 설명글 앞부분
  img_url: string | null           // 대표 이미지 (없으면 null)
}

/** 실록 기사 요약 자료 (kind === 'sillok') */
export interface SillokAgentSource extends AgentSourceBase {
  kind: 'sillok'
  article_id: string
  date: string                     // 예: "중종실록 20년 5월 4일"
  summary: string                  // AI가 만든 한글 요약
  tomb: string | null              // 관련 능 (없으면 null)
  url: string | null               // 국사편찬위원회 원문 주소
}

/** kind 값으로 두 종류를 구분하는 타입 (TypeScript가 kind를 보고 알맞은 항목만 쓰게 해줘요) */
export type AgentSource = HeritageAgentSource | SillokAgentSource

export interface AgentResponse {
  answer: string
  cited: string[]                  // 답변에 쓰인 자료 이름들
  model: string
  steps: AgentStep[]               // Agent가 한 일
  sources: AgentSource[]
  guard: string | null             // 안전장치 개입: 'nudged' | 'replaced' | null
  retried: boolean                 // 포기하려다 한 번 더 찾았으면 true
}
