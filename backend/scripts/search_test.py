# search_test.py
# ------------------------------------------------------------
# 사용자의 "질문"을 임베딩한 뒤, heritage_chunks 테이블에서
# 의미가 가장 비슷한 유산 설명 N개를 찾아 보여주는 테스트 스크립트예요.
# (RAG의 "R = Retrieval(검색)" 부분이에요. LLM 답변은 이 다음 단계!)
#
# 실행 방법: python search_test.py
#           python search_test.py "경복궁의 정문은 어디야?"
# ------------------------------------------------------------

import os
import sys
import psycopg2
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai.types import EmbedContentConfig

# --- 경로/환경변수: embed_and_store.py와 똑같은 방식 ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# override=True: 터미널에 같은 이름의 환경변수가 남아 있어도 .env 파일의 값을 항상 우선해서 사용해요.
# (기본값 False면 터미널 값이 .env보다 우선해서, 모델 설정이 헷갈리는 일이 생겨요.)
load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=True)

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5432"),
    "dbname": os.environ.get("DB_NAME", "postgres"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", "postgres"),
}

EMBEDDING_MODEL = "gemini-embedding-001"  # ⚠ 저장할 때와 반드시 같은 모델!
EMBEDDING_DIM = 768                        # ⚠ 저장할 때와 반드시 같은 차원!
TOP_K = 10                                  # 가장 비슷한 몇 개를 가져올지


def embed_query(question):
    """질문 1개를 768차원 벡터로 바꿔요.
    핵심: 저장할 때는 RETRIEVAL_DOCUMENT, 질문할 때는 RETRIEVAL_QUERY!
    (모델이 '이건 찾는 쪽 글'임을 알고 더 잘 맞는 벡터를 만들어줘요.)"""
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=question,
        config=EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=EMBEDDING_DIM,
        ),
    )
    return response.embeddings[0].values   # 숫자 768개짜리 리스트


def search(question, top_k=TOP_K):
    """질문과 가장 비슷한 유산 top_k개를 DB에서 찾아 반환해요."""
    query_vec = embed_query(question)
    # 파이썬 리스트 -> pgvector가 읽는 문자열 "[0.1,0.2,...]"
    vec_literal = "[" + ",".join(str(v) for v in query_vec) + "]"

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    # <=> 는 pgvector의 "코사인 거리" 연산자예요. 거리가 작을수록 의미가 비슷해요.
    # 그래서 거리 오름차순으로 정렬해 앞에서 top_k개만 가져와요.
    # 1 - 거리 = 유사도(1에 가까울수록 비슷)
    cur.execute(
        """
        SELECT gung_name, contents_kor, chunk_text,
               1 - (embedding <=> %s::vector) AS similarity
        FROM heritage_chunks
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (vec_literal, vec_literal, top_k),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


if __name__ == "__main__":
    # 터미널에서 질문을 따로 안 주면 기본 질문을 사용해요.
    question = sys.argv[1] if len(sys.argv) > 1 else "창덕궁의 정문은 무엇인가요?"
    print(f"질문: {question}\n")
    for rank, (gung, name, text, sim) in enumerate(search(question), start=1):
        print(f"[{rank}위] {gung} - {name}  (유사도 {sim:.3f})")
        print(f"      {text[:80]}...\n")
