# eval_search.py
# ------------------------------------------------------------
# 여러 개의 평가 질문을 한 번에 검색해 보고,
# "정답 유산이 몇 위에 나왔는지"를 표로 보여주는 스크립트예요.
# 검색 품질을 숫자로 재서, 개선 전/후를 비교할 때 써요.
#
# 사용 방법 (backend 폴더에서):
#   python scripts\eval_search.py                       # 하이브리드 — 실제 서비스(rag.py)와 같은 검색 (기본 rrf)
#   python scripts\eval_search.py --kw all              # 키워드 점수를 모든 질문에 적용 (기본은 왕릉 질문에만)
#   python scripts\eval_search.py --method vector       # 예전 방식(벡터만) — 비교 기준선
#   python scripts\eval_search.py --method weighted     # 가중 합
#   python scripts\eval_search.py --alpha 0.10          # 키워드 가중치를 바꿔 보기 (기본 0.15)
#   ※ 질문 벡터는 data/eval/query_vec_cache.json에 저장해 둬서, 방식·alpha를 바꿔 다시 돌려도
#     임베딩 API는 처음 한 번만 써요. (질문을 새로 추가했을 때만 그 질문만 호출)
#   결과 파일: data/eval/search_eval_<방식>[_a<alpha>].csv  (방식별로 따로 저장돼서 비교할 수 있어요)
#
# 질문을 추가/수정하고 싶으면 아래 EVAL_SET 목록만 고치면 돼요.
# ------------------------------------------------------------

import argparse
import csv
import json
import sys
import time
from pathlib import Path

# search_test.py에 이미 만들어 둔 설정과 함수를 그대로 재사용해요. (같은 scripts/ 폴더에 있어야 해요)
from search_test import embed_query, PROJECT_ROOT

# 실제 서비스와 같은 검색(rag.py의 search_debug)으로 평가해야 점수가 서비스 품질을 말해줘요.
sys.path.insert(0, str(PROJECT_ROOT))   # backend/ 폴더를 import 경로에 추가 (rag.py, hybrid_search.py가 있는 곳)
import rag
import hybrid_search

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
    # --- 경희궁 (경희궁지 1건 수집 후 추가) ---
    ("경희궁은 언제 지어졌어?",                 "경희궁",   "경희궁지",           "설명형"),
    ("경희궁의 원래 이름은 뭐였어?",            "경희궁",   "경희궁지",           "설명형"),
    # --- 조선왕릉: 이름형 (질문에 능 이름이 들어 있어요) ---
    ("동구릉에 대해 알려줘",                    "조선왕릉", "구리 동구릉",        "이름형"),
    ("영월 장릉은 어떤 곳이야?",                "조선왕릉", "영월 장릉",          "이름형"),
    # --- 조선왕릉: 설명형 (능 이름 없이 인물·사건으로 묻는 질문) ---
    ("단종의 무덤은 어디에 있어?",              "조선왕릉", "영월 장릉",          "설명형"),
    ("단종의 왕비 정순왕후의 능은?",            "조선왕릉", "남양주 사릉",        "설명형"),
    ("사도세자의 무덤은 어디야?",               "조선왕릉", "화성 융릉과 건릉",   "설명형"),
    ("세조가 묻힌 능은?",                       "조선왕릉", "남양주 광릉",        "설명형"),
    ("경종의 무덤은?",                          "조선왕릉", "서울 의릉",          "설명형"),  # 영릉 문서에도 '의릉'이 나와 경쟁함(어려움)
    ("태조의 건원릉이 있는 곳은?",              "조선왕릉", "구리 동구릉",        "설명형"),  # 헌릉 문서에도 '건원릉'이 나와 경쟁함(어려움)
    ("고종과 명성황후가 함께 묻힌 능은?",      "조선왕릉", "남양주 홍릉과 유릉", "설명형"),
    ("문정왕후의 무덤은 어디야?",               "조선왕릉", "서울 태릉과 강릉",   "설명형"),
    # --- 조선왕릉: 별칭형 (본문에 없는 표현으로 묻는 질문 → 가장 어려워요) ---
    ("세종대왕릉(영릉)은 어디에 있어?",         "조선왕릉", "여주 영릉과 영릉",   "별칭형"),
    # --- 궁궐 개요 ---
    ("경복궁은 언제 누가 세웠어?",              "경복궁",   "개요",               "설명형"),
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


VEC_CACHE_PATH = PROJECT_ROOT / "data" / "eval" / "query_vec_cache.json"


def load_vec_cache():
    """이미 임베딩한 질문 벡터를 파일에서 읽어요. (없으면 빈 딕셔너리)"""
    if VEC_CACHE_PATH.exists():
        return json.loads(VEC_CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def get_query_vec(question, cache):
    """질문 벡터를 돌려줘요. 캐시에 있으면 API를 안 쓰고, 없으면 임베딩해서 캐시에 저장해요."""
    if question not in cache:
        cache[question] = embed_with_retry(question)
        VEC_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        VEC_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        time.sleep(SLEEP_BETWEEN_QUESTIONS)     # API를 실제로 쓴 경우에만 쉬어요
    return cache[question]


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
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", choices=["weighted", "rrf", "vector"], default=rag.HYBRID_METHOD,
                    help="rrf=순위 합치기 / weighted=가중 합 / vector=예전 방식 (기본: 서비스(rag.py)와 같은 방식)")
    ap.add_argument("--kw", choices=["all", "tomb"], default="tomb",
                    help="tomb=왕릉 질문에만 키워드 점수 적용 (기본, hybrid_search.KW_LABELS) / all=모든 질문에 적용")
    ap.add_argument("--alpha", type=float, default=None, help="키워드 가중치(기본 hybrid_search.ALPHA)")
    args = ap.parse_args()
    if args.alpha is not None:
        hybrid_search.ALPHA = args.alpha
    if args.kw == "all":
        hybrid_search.KW_LABELS = None
    print(f"검색 방식: {args.method}" + (f" (alpha={hybrid_search.ALPHA})" if args.method == "weighted" else "")
          + (" / 키워드: 왕릉 질문에만" if args.kw == "tomb" else " / 키워드: 모든 질문"))

    cache = load_vec_cache()
    rows = []   # 질문별 결과를 모아 둘 리스트
    for i, (question, gung, name, qtype) in enumerate(EVAL_SET, start=1):
        print(f"[{i}/{len(EVAL_SET)}] {question}")
        hits, info = rag.search_debug(question, top_k=TOP_K, method=args.method,
                                       query_vec=get_query_vec(question, cache))
        results = [(h["gung_name"], h["name"], h["similarity"]) for h in hits]   # (궁, 유산명, 벡터 유사도)
        rank = find_rank(results, gung, name)
        top1 = f"{results[0][0]} {results[0][1]}"
        # 정답이 있으면 정답 유산의 점수를, 없으면 1위의 점수를 기록해요.
        sim = results[(rank or 1) - 1][2]
        rows.append({
            "type": qtype, "question": question, "answer": f"{gung} {name}",
            "rank": rank, "top1": top1, "similarity": round(sim, 3),
            "top1_sim": round(results[0][2], 3),
            "scope": info["scope"],                       # 질문 분류 결과 (어떤 범위로 검색했는지)
        })

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
    suffix = (f"_a{hybrid_search.ALPHA}" if args.method == "weighted" and args.alpha is not None else "") \
             + ("_kwall" if args.kw == "all" else "")
    out_path = out_dir / f"search_eval_{args.method}{suffix}.csv"
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n결과를 저장했어요: {out_path}")


if __name__ == "__main__":
    main()
