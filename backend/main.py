# main.py
# ------------------------------------------------------------
# FastAPI 웹 서버예요. 프론트엔드(React)가 질문을 보내면 rag.py로 답을 만들어 돌려줘요.
#
#   브라우저(React)  --POST /api/ask {"question": "..."}-->  main.py  -->  rag.answer()
#                    <--  {"answer": "...", "sources": [...]} --
#
# 서버 실행 방법 (backend 폴더에서):
#   uvicorn main:app --reload --port 8000
# 실행 후 브라우저에서 http://localhost:8000/docs 를 열면
# 코드를 안 짜고도 질문을 직접 보내 볼 수 있는 시험 화면이 나와요.
# ------------------------------------------------------------

import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

import rag      # 검색 + 답변 생성 로직 (같은 backend/ 폴더의 rag.py). 이때 .env도 함께 불러와져요.

logger = logging.getLogger("heritage")      # 서버 터미널에 오류 내용을 남기기 위한 기록 도구예요.


# ------------------------------------------------------------
# 1. 앱 만들기 + CORS 설정
# ------------------------------------------------------------
app = FastAPI(
    title="Heritage RAG API",
    description="조선 궁궐·종묘 문화유산에 대해 질문하면, 검색된 자료를 근거로 답변과 출처를 돌려줘요.",
    version="0.1.0",
)

# CORS란? 브라우저는 보안 때문에 "다른 주소(포트)의 서버"로 보내는 요청을 기본으로 막아요.
#   프론트(localhost:5173)에서 백엔드(localhost:8000)로 요청하려면, 백엔드가 "5173에서 오는 요청은 허용"이라고
#   미리 알려줘야 해요. 그 허용 목록이 아래예요.
# 나중에 배포하면 .env에 CORS_ORIGINS=https://내사이트주소 처럼 쉼표로 구분해 추가하면 돼요.
DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"     # Vite 개발 서버의 기본 주소
allowed_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", DEFAULT_ORIGINS).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ------------------------------------------------------------
# 2. 요청/응답의 '모양' 정의 (pydantic)
# ------------------------------------------------------------
# pydantic 모델은 "이런 모양의 데이터만 받겠다/돌려주겠다"는 약속이에요.
# 모양이 안 맞으면 FastAPI가 알아서 422 오류를 돌려주고, /docs 화면에도 이 설명이 자동으로 나와요.
# (프론트엔드 TypeScript의 타입도 이 모양을 그대로 따라 만들면 돼요.)
class AskRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=1,
        max_length=300,          # 너무 긴 질문은 무료 사용량을 낭비하고 비용도 늘리니 제한해요.
        description="궁궐·종묘에 대한 질문",
        examples=["경복궁의 정문은 어디야?"],
    )

    @field_validator("question")
    @classmethod
    def strip_question(cls, v):
        v = v.strip()            # 앞뒤 공백 제거
        if not v:                # 공백만 보낸 경우를 막아요.
            raise ValueError("질문을 입력해 주세요.")
        return v


class Source(BaseModel):
    gung_name: str = Field(description="궁 이름 (예: 경복궁)")
    name: str = Field(description="유산 이름 (예: 광화문)")
    similarity: float = Field(description="질문과의 유사도 (1에 가까울수록 비슷)")
    img_url: str | None = Field(description="대표 이미지 주소 (없으면 null)")
    excerpt: str = Field(description="참고한 설명글의 앞부분 미리보기")
    cited: bool = Field(description="AI가 답변의 출처로 직접 적은 유산이면 true")


class AskResponse(BaseModel):
    answer: str = Field(description="AI 답변 (출처 줄은 sources에 따로 있어요)")
    model: str = Field(description="실제로 답한 AI 모델 이름")
    sources: list[Source] = Field(description="검색된 참고 자료 목록 (유사도 높은 순)")


# ------------------------------------------------------------
# 3. API 엔드포인트
# ------------------------------------------------------------
# 아래 함수들은 일부러 'async def'가 아니라 그냥 'def'로 만들었어요.
# 이 프로젝트의 DB(psycopg2)와 Gemini 라이브러리는 "한 번에 하나씩 기다리는(동기)" 방식이라,
# FastAPI가 'def' 함수는 별도 작업 공간(스레드)에서 실행해 줘야 한 사용자가 기다리는 동안
# 다른 사용자의 요청이 같이 멈추지 않아요.

@app.get("/api/health", summary="서버 상태 확인")
def health():
    """서버가 켜져 있고 DB에 연결되는지 확인해요. 저장된 유산 개수도 함께 보여줘요."""
    try:
        chunk_count = rag.count_chunks()
    except Exception:
        logger.exception("health 확인 중 DB 오류")      # 자세한 오류는 서버 터미널에만 남겨요.
        raise HTTPException(status_code=503, detail="DB에 연결할 수 없어요.")
    return {
        "status": "ok",
        "chunk_count": chunk_count,                      # 지금까지 127이 나오는지 확인해 보세요.
        "llm_model": rag.LLM_MODEL,
        "fallback_model": rag.FALLBACK_MODEL,
        "embedding_model": rag.EMBEDDING_MODEL,
    }


@app.post("/api/ask", response_model=AskResponse, summary="질문하기")
def ask(req: AskRequest):
    """질문을 받아 → 비슷한 유산을 검색하고 → AI가 그 자료만 근거로 답변과 출처를 돌려줘요."""
    try:
        return rag.answer(req.question)
    except rag.RagError as e:
        # 예상했던 문제(한도 초과, 서버 바쁨, DB 오류 등): 사용자용 안내 문구와 알맞은 상태 코드로 응답해요.
        logger.warning("RAG 오류 %s: %s", type(e).__name__, e.message)
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception:
        # 예상하지 못한 오류: 자세한 내용(내부 정보 포함)은 서버 터미널에만 남기고, 사용자에게는 일반 문구만 보여줘요.
        logger.exception("질문 처리 중 예상치 못한 오류")
        raise HTTPException(status_code=500, detail="서버에서 알 수 없는 오류가 발생했어요.")
