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
