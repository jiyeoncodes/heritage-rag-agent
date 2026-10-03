# eval_search.py
# ------------------------------------------------------------
# 여러 개의 평가 질문을 한 번에 검색해 보고,
# "정답 유산이 몇 위에 나왔는지"를 표로 보여주는 스크립트예요.
# 검색 품질을 숫자로 재서, 개선 전/후를 비교할 때 써요.
#
# 사용 방법:
#   python eval_search.py
#
# 질문을 추가/수정하고 싶으면 아래 EVAL_SET 목록만 고치면 돼요.
# ------------------------------------------------------------

import csv
import time
import psycopg2
from pathlib import Path

# search_test.py에 이미 만들어 둔 설정과 함수를 그대로 재사용해요. (같은 scripts/ 폴더에 있어야 해요)
from search_test import DB_CONFIG, embed_query, PROJECT_ROOT

TOP_K = 10                      # 각 질문마다 상위 몇 개까지 가져올지
SLEEP_BETWEEN_QUESTIONS = 1.0   # 질문 사이 대기(초). 무료 API 한도(분당 요청 수)를 지키기 위해서예요.
MAX_RETRIES = 4                 # 429(한도 초과) 시 다시 시도할 횟수
RETRY_WAIT = 30                 # 재시도 전 기다릴 시간(초)

# ------------------------------------------------------------
# 평가 질문 세트
# (질문, 정답 궁 이름, 정답 유산 이름, 질문 종류)
#   - "별칭형": 본문에 없는 말(정문 등)로 묻는 질문 → 가장 어려워요
#   - "이름형": 유산 이름이 질문에 들어 있는 질문 → 가장 쉬워요
#   - "설명형": 이름 없이 특징으로 묻는 질문
# ※ 정답은 data/processed CSV에 실제로 있는 (궁, 유산명)이에요.
# ------------------------------------------------------------
EVAL_SET = [
    ("경복궁의 정문은 어디야?",                  "경복궁", "광화문",     "별칭형"),
    ("창덕궁의 정문은 어디야?",                  "창덕궁", "돈화문",     "별칭형"),
    ("창경궁의 정문은 어디야?",                  "창경궁", "홍화문",     "별칭형"),
    ("덕수궁의 정문은 어디야?",                  "덕수궁", "대한문",     "별칭형"),
    ("광화문은 어떤 문이야?",                    "경복궁", "광화문",     "이름형"),
    ("경회루에 대해 알려줘",                     "경복궁", "경회루",     "이름형"),
    ("석조전은 어떤 건물이야?",                  "덕수궁", "석조전",     "이름형"),
    ("창경궁의 대온실은 무엇인가요?",            "창경궁", "대온실",     "이름형"),
    ("경복궁 북쪽에 있는 문은?",                 "경복궁", "신무문",     "설명형"),
    ("경복궁에서 연못 위에 지은 큰 누각은?",     "경복궁", "경회루",     "설명형"),
    ("경복궁에서 왕비가 지내던 침전은?",         "경복궁", "교태전",     "설명형"),
    ("십장생이 그려진 굴뚝은 어디에 있어?",      "경복궁", "십장생 굴뚝", "설명형"),
    ("창경궁에 있는 해시계는?",                  "창경궁", "앙부일구",   "설명형"),
    ("창덕궁에서 왕의 즉위식 같은 큰 행사를 하던 건물은?", "창덕궁", "인정전", "설명형"),
    ("종묘에서 제사를 지내는 가장 중요한 건물은?", "종묘",  "정전",       "설명형"),
]


def embed_with_retry(question):
    """질문 임베딩. 한도 초과(429)면 잠깐 쉬었다가 다시 시도해요."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return embed_query(question)
        except Exception as e:
            msg = str(e)
            is_rate_limit = "429" in msg or "RESOURCE_EXHAUSTED" in msg
            if not is_rate_limit or attempt == MAX_RETRIES:
                raise
            print(f"    ! 한도 초과(429). {RETRY_WAIT}초 후 재시도... ({attempt}/{MAX_RETRIES})")
            time.sleep(RETRY_WAIT)


def search_top_k(cur, query_vec, top_k):
    """DB에서 질문 벡터와 가장 비슷한 top_k개를 (궁, 유산명, 유사도) 리스트로 반환해요."""
    vec_literal = "[" + ",".join(str(v) for v in query_vec) + "]"
    cur.execute(
        """
        SELECT gung_name, contents_kor, 1 - (embedding <=> %s::vector) AS similarity
        FROM heritage_chunks
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (vec_literal, vec_literal, top_k),
    )
    return cur.fetchall()


def find_rank(results, gung, name):
    """결과 리스트에서 정답(궁+유산명)이 몇 번째인지 반환해요. 없으면 None."""
    for rank, (g, n, _sim) in enumerate(results, start=1):
        if g == gung and n == name:
            return rank
    return None


def pad(text, width):
    """한글은 화면에서 글자 하나가 2칸을 차지해서, 표가 안 틀어지게 직접 폭을 맞춰요."""
    used = sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)
    return text + " " * max(0, width - used)


def main():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    rows = []   # 질문별 결과를 모아 둘 리스트
    for i, (question, gung, name, qtype) in enumerate(EVAL_SET, start=1):
        print(f"[{i}/{len(EVAL_SET)}] {question}")
        results = search_top_k(cur, embed_with_retry(question), TOP_K)
        rank = find_rank(results, gung, name)
        top1 = f"{results[0][0]} {results[0][1]}"
        # 정답이 있으면 정답 유산의 점수를, 없으면 1위의 점수를 기록해요.
        sim = results[(rank or 1) - 1][2]
        rows.append({
            "type": qtype, "question": question, "answer": f"{gung} {name}",
            "rank": rank, "top1": top1, "similarity": round(sim, 3),
            "top1_sim": round(results[0][2], 3),
        })
        time.sleep(SLEEP_BETWEEN_QUESTIONS)

    cur.close()
    conn.close()

    # ---------------- 표 출력 ----------------
    print("\n" + "=" * 100)
    print(pad("종류", 8) + pad("질문", 46) + pad("정답", 18) + pad("정답순위", 10) + "1위 결과")
    print("-" * 100)
    for r in rows:
        rank_text = f"{r['rank']}위" if r["rank"] else f"{TOP_K}위 밖"
        mark = "O" if r["rank"] == 1 else ("△" if r["rank"] else "X")   # O=1위, △=2~10위, X=못 찾음
        print(pad(r["type"], 8) + pad(r["question"], 46) + pad(r["answer"], 18)
              + pad(f"{mark} {rank_text}", 10) + f"{r['top1']} ({r['top1_sim']})")

    # ---------------- 요약 점수 ----------------
    def summarize(subset, label):
        n = len(subset)
        if n == 0:
            return
        hit1 = sum(1 for r in subset if r["rank"] == 1)
        hit3 = sum(1 for r in subset if r["rank"] and r["rank"] <= 3)
        hitk = sum(1 for r in subset if r["rank"])
        # MRR: 정답이 1위면 1점, 2위면 0.5점, 3위면 0.33점... 못 찾으면 0점의 평균 (높을수록 좋아요)
        mrr = sum(1 / r["rank"] for r in subset if r["rank"]) / n
        print(pad(label, 10) + f"1위 {hit1}/{n}   3위 안 {hit3}/{n}   {TOP_K}위 안 {hitk}/{n}   MRR {mrr:.2f}")

    print("\n=== 요약 ===")
    summarize(rows, "전체")
    for qtype in ["이름형", "설명형", "별칭형"]:
        summarize([r for r in rows if r["type"] == qtype], qtype)

    # ---------------- CSV 저장 (개선 전/후 비교용) ----------------
    out_dir = PROJECT_ROOT / "data" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "search_eval_result.csv"
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n결과를 저장했어요: {out_path}")


if __name__ == "__main__":
    main()
