# frontend (React + TypeScript + Vite)

```
cd frontend
npm install
npm run dev      # http://localhost:5173  (백엔드: backend 폴더에서 uvicorn main:app --reload --port 8000)
npm run build    # 타입 검사 + 배포용 빌드
npm run lint
```
백엔드 주소를 바꾸려면 `.env.example`을 `.env.local`로 복사해 `VITE_API_BASE_URL`을 수정하세요.
