# sillok_search.py
# ------------------------------------------------------------
# 실록 기사 검색 함수 search_sillok() — 나중에 Agent의 "도구(tool)" 하나가 될 부분이에요.
#
# 하는 일
#   ① 질문을 숫자(벡터)로 바꾼다            (rag.embed_query, 질문용 RETRIEVAL_QUERY 설정)
#   ② heritage_chunk 중 "실록 요약" 청크만 골라, 질문과 의미가 가까운 순서로 찾는다
#   ③ 왕(reign) · 능(tomb) 필터가 있으면 그 조건에 맞는 기사만 대상으로 한다
#   ④ 기사 정보(제목, 날짜, 요약, 원문 일부, 출처 주소)를 묶어 돌려준다
#
# 왜 왕 필터가 필요한가: 요약은 한글이고 한문 원문에는 왕 이름이 잘 안 나와서,
#   "세종 때 ..." 같은 질문은 벡터만으로는 다른 왕의 기사와 섞일 수 있어요.
#
# 실행 (backend 폴더에서):
#   python sillok_search.py "세종의 능을 옮긴 이유는?"
#   python sillok_search.py "능에 제사 지낸 기록" --reign 정조 --top 5
#   python sillok_search.py "영릉 관련 기록" --tomb 영릉(세종)
# ------------------------------------------------------------

import argparse
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

import rag                                       # 질문 임베딩(embed_query)과 재시도 로직을 그대로 재사용

BASE = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE / ".env", override=True)
DB = dict(host=os.environ.get("DB_HOST", "localhost"), port=os.environ.get("DB_PORT", "5432"),
          dbname=os.environ.get("DB_NAME", "postgres"), user=os.environ.get("DB_USER", "postgres"),
          password=os.environ.get("DB_PASSWORD", "postgres"))

CHUNK_TYPE = "실록 요약"                          # embed_sillok.py 에서 저장한 청크 종류


def search_sillok(question, top_k=5, reign=None, tomb=None):
    """질문과 가까운 실록 기사 top_k개를 돌려줘요.

    reign: 왕 이름 일부 (예: "세종" → '세종실록'). 없으면 모든 왕.
    tomb : 유산 이름 일부 (예: "영릉(세종)"). tomb_detail 에 포함된 기사만.
    반환 : 딕셔너리 리스트 (유사도 높은 순)
    """
    vec = "[" + ",".join(str(v) for v in rag.embed_query(question)) + "]"   # 파이썬 리스트 → pgvector 문자열

    where = ["c.chunk_type = %s", "c.article_id IS NOT NULL"]     # 실록 청크만 (유산 청크 제외)
    params = [CHUNK_TYPE]
    if reign:
        where.append("a.reign_title LIKE %s")                      # '세종' → '세종%'
        params.append(reign + "%")
    if tomb:
        where.append("a.tomb_detail LIKE %s")
        params.append("%" + tomb + "%")

    sql = f"""
        SELECT a.article_id, a.reign_title, a.date_label, a.title, a.summary_kor,
               a.tomb_detail, a.source_url, LEFT(a.text_hanja, 200),
               1 - (c.embedding <=> %s::vector) AS similarity      -- 코사인 거리 → 유사도(1에 가까울수록 비슷)
        FROM heritage_chunk c
        JOIN sillok_article a ON a.article_id = c.article_id
        WHERE {' AND '.join(where)}
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s"""
    conn = psycopg2.connect(**DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [vec] + params + [vec, top_k])
            rows = cur.fetchall()
    finally:
        conn.close()

    keys = ["article_id", "reign_title", "date_label", "title", "summary", "tomb_detail",
            "source_url", "hanja_excerpt", "similarity"]
    return [dict(zip(keys, r)) for r in rows]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--reign", default=None, help="왕 이름 일부 (예: 세종)")
    ap.add_argument("--tomb", default=None, help="유산 이름 일부 (예: 영릉(세종))")
    ap.add_argument("--top", type=int, default=5)
    a = ap.parse_args()
    print(f"질문: {a.question}  (왕={a.reign}, 능={a.tomb})\n")
    for i, h in enumerate(search_sillok(a.question, a.top, a.reign, a.tomb), 1):
        print(f"[{i}위] {h['date_label']} | {h['title']}  (유사도 {h['similarity']:.3f}, {h['tomb_detail'] or '-'})")
        print(f"      {h['summary'][:110]}...")
        print(f"      {h['source_url']}\n")
