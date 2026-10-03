// vite.config.ts
// ------------------------------------------------------------
// Vite(개발 서버 + 빌드 도구) 설정 파일이에요.
// ------------------------------------------------------------
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // strictPort: 5173번 포트가 이미 사용 중이면 다른 번호(5174 등)로 몰래 바꾸지 않고 오류를 내요.
    // 백엔드(main.py)는 "localhost:5173"에서 오는 요청만 허용(CORS)해 두었기 때문에,
    // 포트가 바뀌면 요청이 막혀서 원인을 찾기 어려워져요.
    strictPort: true,
  },
})
