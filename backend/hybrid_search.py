# hybrid_search.py
# ------------------------------------------------------------
# "하이브리드 검색"에 쓰는 순수 계산 함수들을 모아 둔 파일이에요.
# (DB나 Gemini API를 전혀 쓰지 않아서, 이 파일만으로 직접 실행·테스트해 볼 수 있어요.)
#
# 전체 흐름 (rag.py의 search_debug()가 이 파일의 함수를 순서대로 불러요)
#
#   질문
#    ① classify_question()   질문 분류: "왕릉 질문이네? / 경복궁 질문이네?" → 검색 범위(scope) 결정
#    ② (rag.py) 벡터 검색     의미가 비슷한 후보를 DB에서 가져옴 (질문 임베딩 + 코사인 유사도)
#    ③ apply_scope()         범위 안의 후보만 남김 (애매하면 전체로 되돌림)
#    ④ keyword_scores()      키워드 점수: 질문 속 단어가 실제로 본문에 들어 있는지 (희귀한 단어일수록 큰 점수)
#    ⑤ fuse()                벡터 점수 + 키워드 점수를 합쳐 최종 순위 결정 (가중 합 / RRF 중 선택)
#
# 왜 필요한가?
#   벡터 검색은 "의미"는 잘 찾지만, 글자가 닮은 다른 이름에 끌려갈 수 있어요.
#   예) "문정왕후의 무덤은?" → 의미가 비슷한 창경궁 "문정전"이 1등, 진짜 정답(태릉과 강릉)은 2등
#       "사도세자의 무덤은?" → 정답(융릉과 건릉)이 4등
#   → ① "무덤" 질문이면 능역 안에서만 찾고, ④ "문정왕후"라는 단어가 실제로 들어 있는 글에 점수를 더 줘요.
#
# 이 파일의 숫자(ALPHA, MIN_SCOPE_SIM 등)는 "평가로 찾는 값"이에요. 바꾸고 eval_search.py를 다시 돌려 확인하세요.
# ------------------------------------------------------------

import math
import re

# ------------------------------------------------------------
# 0. 조절 가능한 설정값
# ------------------------------------------------------------
ALPHA = 0.15            # 가중 합에서 키워드 점수(0~1)에 곱하는 값. 클수록 키워드를 더 믿어요.
RRF_K = 60              # RRF(순위 합치기)의 상수. 보통 60을 써요. 클수록 순위 차이의 영향이 작아져요.
MIN_SCOPE_SIM = 0.60    # 범위 안 1등의 유사도가 이보다 낮으면 "범위를 잘못 잡았다"고 보고 전체로 되돌려요.
MAX_DF_RATIO = 0.30     # 후보 중 30%보다 많은 글에 나오는 단어("경복궁", "정문" 등)는 키워드로 쓰지 않아요.
                        # (너무 흔한 단어는 정답을 가려내는 힘이 없고, 오히려 엉뚱한 글에 점수를 줘요.)

# 키워드 점수를 적용할 범위. None이면 모든 질문에 적용, {"왕릉"}처럼 적으면 그 범위 질문에만 적용해요.
#   (2026-10-06 평가: 모든 질문에 적용하면 왕릉 질문은 좋아지지만 궁궐의 "정문" 같은 별칭 질문이 3등→5등으로 밀렸어요.
#    왕릉 질문에만 적용하면 왕릉 개선은 그대로 두고 궁궐 질문은 원래 순위를 지켰어요 → 기본값을 {"왕릉"}으로 정함.
#    ※ 29문항으로 정한 값이라 새 질문으로 한 번 더 검증이 필요해요.)
KW_LABELS = {"왕릉"}

# 질문에 이 이름이 있으면 그 궁(group_name)으로 범위를 좁혀요. (DB의 group_name과 글자가 같아야 해요)
GROUP_NAMES = ["경복궁", "창덕궁", "창경궁", "덕수궁", "경희궁", "종묘"]

# "왕릉 질문"으로 판단하는 표현:
#   무덤/왕릉/능역/묻힌/안장 이 들어 있거나, "동구릉·광릉·영릉"처럼 ○릉으로 끝나는 이름이 있거나,
#   "정순왕후의 능은?"처럼 단독 낱말 "능"(+조사)이 있을 때. ("능력"처럼 다른 낱말은 걸리지 않게 뒤를 확인해요.)
TOMB_PATTERN = re.compile(
    r"무덤|왕릉|능역|묻힌|묻혔|묻혀|안장|[가-힣]릉"
    r"|(?<![가-힣])능(?:은|는|이|가|을|를|도|에|과|와|으로)?(?![가-힣])"
)
TOMB_ENTITY_TYPE = "능역"   # DB heritage.entity_type 값 (왕릉 18건)

# 질문 낱말 끝의 조사(은/는/이/가...)를 떼기 위한 목록. 긴 것부터 확인해야 "에서"가 "서"보다 먼저 잡혀요.
PARTICLES = sorted([
    "에서는", "으로는", "이라고", "에게서", "에서", "으로", "에게", "까지", "부터", "이란", "이라",
    "입니다", "인가요", "이야", "에는", "은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "도", "로", "만", "야",
], key=len, reverse=True)


# 키워드로 쓰지 않을 "질문용 말투" 낱말. ("어디", "있어"는 모든 질문에 나와서 정답을 가려내는 힘이 없어요.)
STOPWORDS = {
    "어디", "어떤", "어떻게", "무엇", "무엇인가", "언제", "누가", "얼마", "대해", "알려줘", "알려", "있어", "있는", "있나",
    "함께", "가장", "중요한", "하던", "지내", "같은", "건물", "곳", "뭐였어", "지어졌어", "세웠어",
    # 왕릉 질문임을 알려 주는 말: 이미 ① 질문 분류가 "왕릉 범위"로 쓰고 있어서 키워드로 또 쓰면 중복이에요.
    "무덤", "왕릉", "능역", "묻힌", "묻혔", "묻혀", "안장",
}


# ------------------------------------------------------------
# ① 질문 분류 (규칙 기반)
# ------------------------------------------------------------
def classify_question(question):
    """질문을 읽고 검색 범위(scope)를 정해요. 모르겠으면 범위 없음(None = 전체 검색)이에요.

    반환 예시:
      {"entity_type": "능역", "groups": None,        "label": "왕릉"}
      {"entity_type": None,   "groups": ["경복궁"], "label": "경복궁"}
      None                                              (분류 못 함 → 전체 검색)

    ※ 왕릉 표현과 궁 이름이 같이 있으면(예: "경복궁에도 무덤이 있어?") 헷갈리니까 범위를 좁히지 않아요.
    """
    is_tomb = bool(TOMB_PATTERN.search(question))
    groups = [g for g in GROUP_NAMES if g in question]

    if is_tomb and groups:
        return None                                   # 서로 충돌 → 안전하게 전체 검색
    if is_tomb:
        return {"entity_type": TOMB_ENTITY_TYPE, "groups": None, "label": "왕릉"}
    if groups:
        return {"entity_type": None, "groups": groups, "label": "+".join(groups)}
    return None


# ------------------------------------------------------------
# ③ 범위 적용 (약한 필터)
# ------------------------------------------------------------
def in_scope(item, scope):
    """후보(딕셔너리) 하나가 범위 안인지 확인해요."""
    if scope["entity_type"] and item["entity_type"] != scope["entity_type"]:
        return False
    if scope["groups"] and item["gung_name"] not in scope["groups"]:
        return False
    return True


def apply_scope(candidates, scope):
    """범위 안의 후보만 남겨요. 아래 경우엔 범위를 포기하고 전체 후보를 그대로 돌려줘요(안전장치).
       - 범위 안에 후보가 하나도 없을 때
       - 범위 안 1등의 벡터 유사도가 MIN_SCOPE_SIM보다 낮을 때 ("범위를 잘못 잡았을 수도 있어요")
    반환: (남긴 후보들, 실제로 쓴 scope 또는 None, 설명 문자열)"""
    if scope is None:
        return candidates, None, "범위 없음"
    kept = [c for c in candidates if in_scope(c, scope)]
    if not kept:
        return candidates, None, f"{scope['label']} 범위에 후보 없음 → 전체"
    best = max(c["similarity"] for c in kept)
    if best < MIN_SCOPE_SIM:
        return candidates, None, f"{scope['label']} 범위 1등 유사도 {best:.2f} < {MIN_SCOPE_SIM} → 전체"
    return kept, scope, f"{scope['label']} 범위 ({len(kept)}건)"


# ------------------------------------------------------------
# ④ 키워드 점수
# ------------------------------------------------------------
def extract_terms(question):
    """질문에서 키워드 후보를 뽑아요.
    예) "문정왕후의 무덤은 어디야?" → ["문정왕후", "무덤"]  (조사를 떼고, 2글자 이상만 남기고, "어디" 같은 질문용 말투는 버림)"""
    terms = []
    for word in re.findall(r"[가-힣A-Za-z0-9]+", question):
        for p in PARTICLES:
            if word.endswith(p) and len(word) > len(p):        # 조사를 떼요. ("광화문은" → "광화문", "능은" → "능")
                word = word[: -len(p)]
                break
        # 떼고 나서 1글자만 남는 낱말("능", "문", "곳")은 너무 흔해서 버려요. 질문용 말투(STOPWORDS)도 버려요.
        if len(word) >= 2 and word not in STOPWORDS and word not in terms:
            terms.append(word)
    return terms


def keyword_scores(question, candidates):
    """후보마다 0~1 사이의 키워드 점수를 계산해서 리스트로 돌려줘요. (후보와 같은 순서)

    계산 방법 (TF-IDF를 아주 단순하게 만든 것):
      1) 질문 단어(term)마다 "후보 중 몇 개의 글에 들어 있는지(df)"를 세요.
      2) df가 0이면 버려요 (본문에 없는 단어). df가 후보의 MAX_DF_RATIO(30%)보다 많으면 버려요 (너무 흔한 단어).
      3) 남은 단어의 가중치 = ln(1 + 후보수/df)  → 적은 글에만 나올수록 큼 ("문정왕후"는 크고 "건물"은 작음)
      4) 글의 점수 = (그 글에 들어 있는 단어들의 가중치 합) / (전체 가중치 합)   → 0~1
    글에 단어가 들어 있는지는 이름(name)과 본문(text)을 합친 문자열에서 '포함 여부'로 봐요."""
    n = len(candidates)
    haystacks = [f"{c['name']} {c['text']}" for c in candidates]
    weights = {}
    for term in extract_terms(question):
        df = sum(1 for h in haystacks if term in h)
        if df == 0 or df / n > MAX_DF_RATIO:
            continue
        weights[term] = math.log(1 + n / df)
    total = sum(weights.values())
    if total == 0:
        return [0.0] * n, {}
    scores = [sum(w for t, w in weights.items() if t in h) / total for h in haystacks]
    return scores, weights


# ------------------------------------------------------------
# ⑤ 점수 합치기
# ------------------------------------------------------------
def fuse(candidates, kw, method="weighted"):
    """벡터 유사도와 키워드 점수를 합쳐서, 최종 점수가 높은 순으로 정렬해 돌려줘요.

    method
      "weighted": 최종 = 벡터 유사도 + ALPHA × 키워드 점수          (점수 크기를 그대로 반영)
      "rrf"     : 최종 = 1/(RRF_K+벡터순위) + 1/(RRF_K+키워드순위)   (순위만 반영. 키워드 점수가 0이면 그 항은 0)
      "vector"  : 최종 = 벡터 유사도 (기존 방식. 비교 기준선)
    각 후보에 "score"(최종 점수)와 "kw"(키워드 점수)를 적어서 돌려줘요."""
    items = []
    for c, k in zip(candidates, kw):
        items.append({**c, "kw": round(k, 4)})

    if method == "weighted":
        for it in items:
            it["score"] = it["similarity"] + ALPHA * it["kw"]
    elif method == "rrf":
        by_vec = sorted(items, key=lambda x: -x["similarity"])
        vec_rank = {id(it): r for r, it in enumerate(by_vec, start=1)}
        by_kw = sorted([it for it in items if it["kw"] > 0], key=lambda x: -x["kw"])
        kw_rank = {id(it): r for r, it in enumerate(by_kw, start=1)}
        for it in items:
            s = 1 / (RRF_K + vec_rank[id(it)])
            if id(it) in kw_rank:
                s += 1 / (RRF_K + kw_rank[id(it)])
            it["score"] = s
    elif method == "vector":
        for it in items:
            it["score"] = it["similarity"]
    else:
        raise ValueError(f"알 수 없는 method: {method}")

    return sorted(items, key=lambda x: -x["score"])


if __name__ == "__main__":
    # 직접 실행하면 분류·단어 추출 예시를 보여줘요. (DB·API 없이 동작)
    for q in ["문정왕후의 무덤은 어디야?", "경복궁의 정문은 어디야?", "석조전은 어떤 건물이야?", "경복궁에도 무덤이 있어?"]:
        print(q, "→ 분류:", classify_question(q), "/ 단어:", extract_terms(q))
