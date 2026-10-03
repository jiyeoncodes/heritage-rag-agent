// src/vite-env.d.ts
// import.meta.env 에서 우리가 쓰는 환경변수(VITE_ 로 시작)의 타입을 알려주는 선언 파일이에요.
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
}
