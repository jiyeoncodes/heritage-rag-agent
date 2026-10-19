# agent_tools.py
# ------------------------------------------------------------
# Agent(LLM)이 "스스로 골라서 부를 수 있는 도구" 3개를 모아 둔 파일이에요.
#
#   search_heritage   궁궐·종묘·왕릉 '유산 설명'을 의미 검색       (기존 rag.search 재사용)
#   search_sillok     조선왕조실록 기사 '요약'을 의미 검색          (sillok_search.search_sillok 재사용)
#   find_tomb_names   "세종", "영릉" 같은 말로 실록 데이터의 정확한 능 이름 찾기 (DB 조회)
#
# 중요: 아래 함수의 "독스트링(함수 설명글)"과 인자 설명이 곧 LLM이 읽는 '도구 사용 설명서'예요.
#       LLM은 이 글만 보고 어떤 도구를 언제 쓸지 정하므로, 설명을 바꾸면 Agent의 행동이 바뀌어요.
#
# 각 도구는 {"ok": True, "results": [...]} 모양의 딕셔너리를 돌려줘요. (LLM에게 그대로 전달돼요)
# 오류가 나도 예외를 밖으로 던지지 않고 {"ok": False, "error": "..."}로 돌려줘서, LLM이 다른 방법을 시도할 수 있게 해요.
# ------------------------------------------------------------

import psycopg2

import rag                    # 질문 임베딩, 유산 검색, DB 접속 정보
import sillok_search          # 실록 요약 검색


def search_heritage(query: str) -> dict:
    """조선 궁궐(경복궁·창덕궁·창경궁·덕수궁·경희궁), 종묘, 조선왕릉의 '현재 문화유산 설명'을 의미로 검색합니다.
    건물·문·능의 위치, 역할, 구조, 특징을 묻는 질문에 사용하세요.
    역사 속 사건이나 인물의 행적(누가 무엇을 했는지, 왜 옮겼는지 등 과거 기록)은 이 도구가 아니라 search_sillok을 쓰세요.

    Args:
        query: 검색할 내용. 예: "경복궁 정문", "창덕궁 후원의 특징"
    """
    try:
        hits = rag.search(query, top_k=5)
    except Exception as e:                                   # 한도 초과·DB 오류 등을 LLM에게 알려줘요
        return {"ok": False, "error": f"유산 검색 실패: {type(e).__name__}"}
    results = [{
        "kind": "heritage",
        "label": f"{h['gung_name']} {h['name']}",             # 출처 표시에 쓸 이름 (예: 경복궁 광화문)
        "text": h["text"][:500],                              # 너무 길면 LLM 입력이 낭비되어 앞부분만
        "similarity": round(h["similarity"], 3),
        "img_url": h.get("img_url"),
    } for h in hits]
    return {"ok": True, "results": results}


def search_sillok(query: str, tomb: str = "", reign: str = "") -> dict:
    """조선왕조실록 기사(한글 요약)를 의미로 검색합니다. 역사 속 사건·인물·제사·능의 이전(천장·천릉)·수리 등
    '과거에 무슨 일이 있었는지'를 묻는 질문에 사용하세요. 결과는 기사 날짜·제목·요약입니다.

    검색어(query)는 질문 문장을 그대로 쓰지 말고, 실록 기사에서 쓰는 말로 바꿔서 쓰세요.
    예: "능을 옮긴 이유" → "영릉 천장 천릉 이장 이유", "능에 제사" → "친제 작헌례 제향".
    능 이름은 '세종의 능' 같은 풀어쓴 말이 아니라 '영릉'처럼 실록에서 쓰는 이름으로 쓰세요.

    Args:
        query: 실록용 검색어. 예: "영릉 천장 천릉 이유"
        tomb: 특정 능의 기사만 보고 싶을 때, find_tomb_names로 확인한 정확한 이름. 예: "영릉(세종)". 모르면 빈 문자열.
        reign: 특정 왕대의 실록만 보고 싶을 때 왕 이름. 예: "예종". 사건이 어느 왕 때 기록됐는지 확실할 때만 쓰고, 모르면 빈 문자열.
            (주의: 세종의 능에 관한 기록이라도 후대 왕의 실록에 있을 수 있어요.)
    """
    try:
        hits = sillok_search.search_sillok(query, top_k=6, reign=reign or None, tomb=tomb or None)
    except Exception as e:
        return {"ok": False, "error": f"실록 검색 실패: {type(e).__name__}"}
    results = [{
        "kind": "sillok",
        "article_id": h["article_id"],                        # 평가 채점용 기사 번호
        "date": h["date_label"],                              # 예: 예종실록 총서 (답변에 날짜만 적혀도 출처로 연결하려고)
        "label": f"{h['date_label']} {h['title']}",           # 예: 예종실록 총서 대신들에게 영릉을 천장할 편부를 의논하게 하다
        "summary": h["summary"],
        "tomb": h["tomb_detail"],
        "similarity": round(h["similarity"], 3),
        "url": h["source_url"],
    } for h in hits]
    note = ""
    if not results and (tomb or reign):
        note = "필터에 맞는 기사가 없습니다. tomb/reign 값을 비우거나 find_tomb_names로 이름을 다시 확인해 보세요."
    return {"ok": True, "results": results, "note": note}


def find_tomb_names(keyword: str) -> dict:
    """실록 데이터에서 쓰는 '정확한 능 이름'을 찾습니다. 사용자가 "세종의 능", "효종 무덤"처럼 인물로 말하거나
    "영릉"처럼 같은 이름의 능이 여러 개일 수 있을 때, search_sillok의 tomb 값을 정하기 전에 먼저 사용하세요.
    결과의 name은 '능이름(인물)' 형식(예: 영릉(세종))이고, articles는 그 능과 관련된 실록 기사 수입니다.

    Args:
        keyword: 인물 이름이나 능 이름의 일부. 예: "세종", "영릉", "정릉"
    """
    sql = """
        SELECT u, COUNT(*) FROM sillok_article,
               LATERAL unnest(string_to_array(tomb_detail, ';')) AS u
        WHERE tomb_detail IS NOT NULL AND u ILIKE %s
        GROUP BY u ORDER BY COUNT(*) DESC LIMIT 20"""
    try:
        conn = psycopg2.connect(**rag.DB_CONFIG)
        try:
            with conn.cursor() as cur:
                cur.execute(sql, ("%" + keyword.strip() + "%",))
                rows = cur.fetchall()
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "error": f"능 이름 조회 실패: {type(e).__name__}"}
    results = [{"name": n, "articles": c} for n, c in rows]
    note = "" if rows else "일치하는 능 이름이 없습니다. 다른 표현으로 다시 찾아보세요."
    # 같은 능 이름(괄호 앞부분)이 여러 인물로 나뉘면 모델이 하나만 고르고 넘어가기 쉬워서, 도구 결과에 직접 경고를 붙여요
    base = {}
    for n, _ in rows:
        base.setdefault(n.split("(")[0], []).append(n)
    same = {b: ns for b, ns in base.items() if len(ns) > 1}
    if same:
        groups = "; ".join(", ".join(ns) for ns in same.values())
        note = (f"이름이 같은 능이 여러 개입니다({groups}). 사용자가 어느 인물의 능인지 말하지 않았다면 "
                "하나만 고르지 말고 각각 search_sillok으로 검색하세요. 답변에서도 능별로 구분해 쓰세요.")
    return {"ok": True, "results": results, "note": note}


# Agent가 쓸 수 있는 도구 목록. {이름: 함수}
TOOLS = {f.__name__: f for f in (search_heritage, search_sillok, find_tomb_names)}
