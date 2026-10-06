# rag.py
# ------------------------------------------------------------
# RAG(검색 + 생성)의 핵심 로직을 모아 둔 파일이에요. (웹 서버 코드는 main.py에 있어요)
#
#   질문
#    ① 질문을 숫자(벡터)로 바꾸기      embed_query()
#    ② DB에서 의미가 비슷한 유산 찾기 + 키워드 점수로 보정(하이브리드)   search() / search_debug()
#    ③ 찾은 글만 보고 LLM이 답변 만들기  build_prompt() + ask_llm()
#    ④ 답변과 출처를 정리해서 돌려주기    answer()
#
# scripts/search_test.py, scripts/answer_test.py에서 이미 실행해 본 코드를
# 웹 서버(FastAPI)에서 쓸 수 있게 정리한 버전이에요.
# 차이점: 오류를 '사용자에게 보여줄 안내 문구'로 바꿔 주는 부분이 추가됐고,
#         결과를 딕셔너리(JSON으로 바꾸기 쉬운 형태)로 돌려줘요.
# ------------------------------------------------------------

import os
import re
import time
from pathlib import Path

import psycopg2                                   # 파이썬에서 PostgreSQL에 접속하는 라이브러리
from dotenv import load_dotenv                    # .env 파일을 읽어 환경변수로 등록해 주는 라이브러리
from google import genai                          # Gemini API 라이브러리
from google.genai.types import EmbedContentConfig, GenerateContentConfig

import hybrid_search                              # 질문 분류 · 키워드 점수 · 점수 합치기 (같은 backend/ 폴더)


# ------------------------------------------------------------
# 0. 설정 불러오기
# ------------------------------------------------------------
# 이 파일은 backend/ 폴더 안에 있으니, .env도 같은 폴더(backend/.env)에서 찾아요.
BACKEND_DIR = Path(__file__).resolve().parent
# override=True: 터미널에 같은 이름의 환경변수가 남아 있어도 .env 파일의 값을 항상 우선해요.
load_dotenv(dotenv_path=BACKEND_DIR / ".env", override=True)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    # 키가 없으면 서버를 켜는 순간 바로 알려줘서, 나중에 엉뚱한 곳에서 오류가 나지 않게 해요.
    raise RuntimeError("GEMINI_API_KEY가 없어요. backend/.env 파일에 GEMINI_API_KEY를 넣어 주세요.")

client = genai.Client(api_key=GEMINI_API_KEY)

# DB 접속 정보 (.env에서 읽고, 없으면 기본값 사용)
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5432"),
    "dbname": os.environ.get("DB_NAME", "postgres"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", "postgres"),
}

EMBEDDING_MODEL = "gemini-embedding-001"   # ⚠ 문서를 저장할 때 쓴 모델과 반드시 같아야 해요!
EMBEDDING_DIM = 768                         # ⚠ DB의 vector(768)과 반드시 같아야 해요!

# 답변을 만드는 LLM. .env의 LLM_MODEL로 바꿀 수 있어요. (평가 결과 3.5-flash-lite로 확정)
LLM_MODEL = os.environ.get("LLM_MODEL", "gemini-3.5-flash-lite")
# 기본 모델이 계속 실패하면 대신 쓸 예비 모델이에요. (무료 한도는 모델별로 따로 세기 때문에 도움이 돼요.)
FALLBACK_MODEL = os.environ.get("LLM_FALLBACK_MODEL", "gemini-3.1-flash-lite")

TOP_K = 5                 # LLM에게 보여줄 참고 자료 개수 (검색 결과 상위 몇 개)

# --- 재시도 설정 (웹 요청은 사용자가 기다리고 있어서, 스크립트보다 빨리 포기해요) ---
MAX_RETRIES = 3           # 일시적 오류일 때 모델 1개당 시도 횟수
BACKOFF_BASE = 2          # 첫 대기(초). 2초 → 4초로 두 배씩 늘어나요.
MAX_WAIT_SECONDS = 10     # 이보다 오래 기다려야 한다면 재시도하지 않고 바로 안내해요.


# ------------------------------------------------------------
# 1. LLM에게 주는 규칙 (프롬프트)
# ------------------------------------------------------------
# ⚠ scripts/answer_test.py의 SYSTEM_INSTRUCTION과 같은 내용이에요.
#   평가(eval_answer.py)로 검증한 규칙이라, 한쪽만 고치면 서로 어긋나요. 고칠 땐 두 곳을 같이 고치세요.
SYSTEM_INSTRUCTION = """당신은 조선의 궁궐(경복궁, 창덕궁, 창경궁, 덕수궁, 경희궁), 종묘, 조선왕릉을 안내하는 해설사입니다.
반드시 아래 [참고 자료]에 적힌 내용만 근거로 답하세요.
규칙:
1. 참고 자료에 근거가 없으면 지어내지 말고 "제공된 자료에서는 확인할 수 없습니다"라고 답하세요.
2. 질문에 쓰인 단어가 자료에 그대로 없어도, 자료의 설명(위치, 역할, 방향 등)으로 합리적으로 판단할 수 있으면
   그 근거를 함께 밝히며 답하세요. 단, 추론한 경우에는 "자료상 ~로 보입니다"처럼 추론임을 드러내세요.
3. 답변은 쉬운 한국어로 3~5문장 이내로 간결하게 쓰세요.
4. 답변 끝에 근거로 사용한 유산을 '출처: [분류 유산명]' 형식으로 적으세요. 분류와 유산명은 참고 자료 머리말
   '[분류] 유산명 - ...'에 적힌 그대로 쓰되, 대괄호 하나 안에 함께 넣으세요.
   올바른 예) 출처: [경복궁 광화문]   출처: [조선왕릉 영월 장릉]
   틀린 예) 출처: [경복궁] 광화문   (대괄호를 둘로 나누지 마세요)   (아래 6번의 경우는 제외)
5. 참고 자료에 실제로 적힌 표현이 아니면 "자료에 명시되어 있다"고 쓰지 마세요.
   추론한 내용은 반드시 "자료상 ~로 보입니다", "추론하면 ~"처럼 추론임을 구분해서 쓰세요.
6. 질문에 대한 답을 참고 자료에서 확인할 수 없으면 "제공된 자료에서는 확인할 수 없습니다."라고
   한 문장만 쓰세요. 질문과 무관한 다른 정보를 덧붙이지 말고, 출처 줄도 쓰지 마세요.
   이 문장 뒤에는 '출처:'나 설명을 포함해 어떤 글도 붙이지 마세요.
7. 조선왕릉 자료는 능 하나가 아니라 여러 능을 묶은 "능역" 설명일 수 있습니다. 질문한 인물의 능이나 무덤이
   참고 자료에 명시되어 있을 때만 그 능역을 답하세요. 인물이 자료에 언급만 되고 무덤에 대한 내용이 없으면
   6번처럼 확인할 수 없다고 답하세요."""


# ------------------------------------------------------------
# 2. 오류 종류 정의
# ------------------------------------------------------------
# 서버에서 "예상할 수 있는 문제"는 상황별 이름표(클래스)를 붙여 두면,
# main.py가 이름표를 보고 적절한 HTTP 상태 코드와 안내 문구로 바꿔서 응답할 수 있어요.
class RagError(Exception):
    """RAG 처리 중 예상 가능한 문제. 사용자에게 보여줄 문구(message)와 HTTP 상태 코드를 가져요."""
    status_code = 500
    message = "답변을 만드는 중 문제가 생겼어요. 잠시 후 다시 시도해 주세요."

    def __init__(self, message=None):
        super().__init__(message or self.message)
        if message:
            self.message = message


class QuotaExceededError(RagError):
    """무료 사용량(하루 한도)을 다 쓴 경우"""
    status_code = 429
    message = "오늘 사용할 수 있는 무료 AI 사용량을 모두 사용했어요. 내일 다시 시도해 주세요."


class ServiceBusyError(RagError):
    """AI 서버가 일시적으로 바쁘거나 분당 한도에 걸린 경우"""
    status_code = 503
    message = "AI 서버가 지금 많이 바빠요. 잠시 후 다시 시도해 주세요."


class DatabaseError(RagError):
    """DB에 연결하지 못했거나 검색 중 DB 오류가 난 경우"""
    status_code = 503
    message = "자료 저장소(DB)에 연결할 수 없어요. 서버 관리자에게 문의해 주세요."


class LlmError(RagError):
    """LLM이 답변을 비워서 돌려준 경우 (안전 필터 등)"""
    status_code = 502
    message = "AI가 답변을 만들지 못했어요. 질문을 조금 바꿔서 다시 시도해 주세요."


def is_daily_quota(msg):
    """'하루 사용량 한도'에 걸린 오류인지 판단해요. (오류 메시지에 PerDay가 들어 있어요.)
    1분을 기다려도 안 풀리고, 다음 날 초기화될 때까지 기다려야 해요."""
    return "PerDay" in msg


def is_retryable(msg):
    """'잠깐 기다리면 풀릴 수 있는 오류'인지 판단해요.
    429(분당 한도) / 503(서버 바쁨)은 재시도하고, 하루 한도(PerDay)나 404(모델 이름 오류)는 재시도해도 소용없어요."""
    if is_daily_quota(msg):
        return False
    return any(k in msg for k in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE"))


def _call_with_retry(func, label):
    """func()를 실행하고, 일시적 오류(429/503)면 잠깐 쉬었다가 다시 실행해요.
    기다리는 시간은 2초 → 4초처럼 점점 늘리고(지수 백오프), MAX_WAIT_SECONDS보다 길게 기다려야 하면 포기해요."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return func()
        except Exception as e:
            msg = str(e)
            if not is_retryable(msg) or attempt == MAX_RETRIES:
                raise
            found = re.search(r"retry in ([\d.]+)s", msg)    # 서버가 "13초 뒤에 다시"라고 알려주면 그 시간만큼
            wait = float(found.group(1)) + 1 if found else BACKOFF_BASE * (2 ** (attempt - 1))
            if wait > MAX_WAIT_SECONDS:
                raise                                          # 사용자를 너무 오래 기다리게 할 수는 없어요.
            print(f"[재시도] {label}: 일시적 오류, {wait:.0f}초 후 다시 시도해요 ({attempt}/{MAX_RETRIES})")
            time.sleep(wait)


# ------------------------------------------------------------
# 3. ① 질문 임베딩 + ② 검색
# ------------------------------------------------------------
def embed_query(question):
    """질문 1개를 768차원 벡터(숫자 768개)로 바꿔요.
    핵심: 문서를 저장할 땐 RETRIEVAL_DOCUMENT, 질문할 땐 RETRIEVAL_QUERY를 써요."""
    def _call():
        response = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=question,
            config=EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=EMBEDDING_DIM,
            ),
        )
        return response.embeddings[0].values
    return _call_with_retry(_call, "임베딩")


# 하이브리드 검색 설정 (계산 로직은 hybrid_search.py에 있어요)
#   rrf : 순위 합치기 (기본)   weighted : 벡터 유사도 + 키워드 점수 가중 합   vector : 예전 방식(벡터만, 비교용)
HYBRID_METHOD = os.environ.get("HYBRID_METHOD", "rrf")      # 2026-10-06 평가: rrf가 가중 합보다 점수가 좋았어요
HYBRID_CANDIDATES = 200     # DB에서 벡터 거리순으로 가져올 후보 수. 지금은 151건뿐이라 사실상 전부예요.
                            # (데이터가 수천 건이 되면 키워드 계산은 DB 쪽으로 옮기는 게 좋아요.)


def _fetch_candidates(query_vec):
    """질문 벡터와 가까운 순서로 후보를 가져와요. 각 후보는 hybrid_search.py가 쓰는 딕셔너리 모양이에요."""
    vec_literal = "[" + ",".join(str(v) for v in query_vec) + "]"   # 파이썬 리스트 → pgvector가 읽는 문자열

    conn = psycopg2.connect(**DB_CONFIG)       # 요청마다 연결을 열고 닫아요. (트래픽이 적은 지금은 이 방식이 가장 단순해요.)
    try:
        with conn.cursor() as cur:
            # <=> 는 pgvector의 '코사인 거리'예요. 작을수록 의미가 비슷해서, 거리 오름차순으로 가져와요.
            # 1 - 거리 = 유사도 (1에 가까울수록 비슷)
            cur.execute(
                """
                SELECT h.group_name, h.name_kor, h.entity_type, c.chunk_text, COALESCE(img.url, ''),
                       1 - (c.embedding <=> %s::vector) AS similarity
                FROM heritage_chunk c
                JOIN heritage h ON h.id = c.heritage_id            -- 청크(설명글+벡터)에 유산 정보(이름·분류)를 붙여요
                LEFT JOIN LATERAL (                                -- 유산마다 "대표 이미지 1장"만 골라 붙여요 (없으면 빈 값)
                    SELECT m.url FROM media m
                     WHERE m.heritage_id = h.id AND m.media_type = 'image'
                     ORDER BY m.sort_order, m.id LIMIT 1) img ON true
                ORDER BY c.embedding <=> %s::vector
                LIMIT %s
                """,
                (vec_literal, vec_literal, HYBRID_CANDIDATES),
            )
            rows = cur.fetchall()
    finally:
        conn.close()                            # 오류가 나도 연결은 반드시 닫아요.

    return [
        {
            "gung_name": gung,
            "name": name,
            "entity_type": entity_type,
            "text": text,                       # 설명글 원문 (머리말 없음. LLM에게 줄 때 build_prompt()가 [분류] 유산명 - 을 붙여요)
            "img_url": img_url or None,         # 빈 문자열이면 None(없음)으로 통일
            "similarity": round(float(sim), 4),
        }
        for gung, name, entity_type, text, img_url, sim in rows
    ]


def search_debug(question, top_k=TOP_K, method=None, query_vec=None):
    """하이브리드 검색. (결과 리스트, 검색 과정 설명 딕셔너리)를 돌려줘요. 평가 스크립트가 과정까지 기록할 때 써요.
       ① 질문 분류 → ② 벡터 검색(후보) → ③ 범위 안 후보만 남기기 → ④ 키워드 점수 → ⑤ 점수 합쳐 정렬
    method: "weighted" | "rrf" | "vector"  (None이면 HYBRID_METHOD 설정 사용)
    query_vec: 질문 벡터를 이미 갖고 있으면 넣어요. (평가에서 같은 질문을 여러 방식으로 비교할 때 API 호출을 아끼려고)"""
    method = method or HYBRID_METHOD
    if query_vec is None:
        query_vec = embed_query(question)
    candidates = _fetch_candidates(query_vec)

    if method == "vector":                      # 예전 방식: 벡터 유사도 순서 그대로
        ranked = hybrid_search.fuse(candidates, [0.0] * len(candidates), "vector")
        info = {"method": method, "scope": "사용 안 함", "terms": {}}
    else:
        scope = hybrid_search.classify_question(question)                          # ① 질문 분류
        kept, used, why = hybrid_search.apply_scope(candidates, scope)             # ③ 범위 적용(애매하면 전체로)
        labels = hybrid_search.KW_LABELS                                           # 키워드를 적용할 범위 (None = 전부)
        if labels is None or (used and used["label"] in labels):
            kw, weights = hybrid_search.keyword_scores(question, kept)             # ④ 키워드 점수
        else:
            kw, weights = [0.0] * len(kept), {}                                    # 이 범위에서는 키워드를 쓰지 않아요
        ranked = hybrid_search.fuse(kept, kw, method)                              # ⑤ 합쳐서 정렬
        info = {"method": method, "scope": why, "terms": {k: round(v, 2) for k, v in weights.items()}}

    hits = [
        {
            "gung_name": c["gung_name"],
            "name": c["name"],
            "text": c["text"],
            "img_url": c["img_url"],
            "similarity": c["similarity"],      # 벡터 유사도 (화면·출처 표시용)
            "score": round(c["score"], 4),      # 최종 점수 (정렬 기준)
            "kw": c["kw"],                      # 키워드 점수
        }
        for c in ranked[:top_k]
    ]
    return hits, info


def search(question, top_k=TOP_K):
    """질문과 가장 관련 있는 유산 top_k개를 찾아 딕셔너리 리스트로 돌려줘요. (answer()가 이 함수를 써요)"""
    hits, _info = search_debug(question, top_k)
    return hits


def count_chunks():
    """heritage_chunk 표에 저장된 청크 개수를 세요. (서버 상태 확인용)"""
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM heritage_chunk")
            return cur.fetchone()[0]
    finally:
        conn.close()


# ------------------------------------------------------------
# 4. ③ LLM으로 답변 생성
# ------------------------------------------------------------
def build_prompt(question, hits):
    """검색 결과를 '[참고 자료] (1)...(5)...' 형태로 이어 붙이고, 질문과 합쳐 LLM에게 줄 글을 만들어요."""
    # 임베딩에는 원문만 넣었으니, 머리말("[분류] 유산명 - ")은 여기서 붙여요. LLM이 출처 이름을 이 머리말에서 가져가요.
    reference = "\n\n".join(f"({i}) [{h['gung_name']}] {h['name']} - {h['text']}" for i, h in enumerate(hits, start=1))
    return f"[참고 자료]\n{reference}\n\n[질문]\n{question}"


def call_model(model, prompt):
    """모델 1개로 LLM을 호출해요. 일시적 오류면 재시도하고, 끝까지 실패하면 오류를 그대로 던져요."""
    def _call():
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.2,     # 낮을수록 지어내기가 줄고 답이 일정해져요. 사실 기반 답변엔 낮게!
            ),
        )
        text = response.text
        if not text or not text.strip():
            raise LlmError()
        return text
    return _call_with_retry(_call, model)


def ask_llm(prompt):
    """기본 모델로 시도하고, 일시적 오류나 하루 한도로 실패하면 예비 모델로 바꿔 한 번 더 시도해요.
    돌려주는 값: (답변 텍스트, 실제로 답한 모델 이름)"""
    try:
        return call_model(LLM_MODEL, prompt), LLM_MODEL
    except Exception as e:
        msg = str(e)
        # 하루 한도(PerDay)는 모델별로 따로 세기 때문에, 예비 모델로 바꾸면 계속 쓸 수 있어요.
        # 404(모델 이름 오류) 같은 건 바꿔도 소용없으니 바로 오류를 알려요.
        can_fallback = (is_retryable(msg) or is_daily_quota(msg)) and FALLBACK_MODEL and FALLBACK_MODEL != LLM_MODEL
        if not can_fallback:
            raise
        print(f"[전환] {LLM_MODEL} 사용 불가 → 예비 모델 {FALLBACK_MODEL}로 바꿔서 시도해요.")
        return call_model(FALLBACK_MODEL, prompt), FALLBACK_MODEL


# ------------------------------------------------------------
# 5. ④ 답변과 출처 정리
# ------------------------------------------------------------
def split_answer_and_citations(reply):
    """LLM 답변에서 '출처: [경복궁 광화문]' 줄을 떼어내요.
    돌려주는 값: (출처 줄을 뺀 본문, 출처로 적힌 이름 리스트)  예: ("...", ["경복궁 광화문"])
    - 출처 형식이 조금 달라도("[경복궁] 광화문", 대괄호 없음) 대괄호를 지우고 쉼표로 나눠서 읽어요.
    - 거절 답변("제공된 자료에서는 ... 확인할 수 없습니다")은 LLM이 규칙을 어기고 출처를 붙여도 떼어 내요."""
    body_lines, cited = [], []
    for line in reply.splitlines():
        found = re.search(r"출처\s*[:：]", line)            # "출처:"가 줄 앞에 있든, 문장 끝에 붙어 있든 찾아요
        if found:
            before = line[: found.start()].strip()           # "출처:" 앞의 글은 본문으로 남겨요
            if before:
                body_lines.append(before)
            names = line[found.end():].replace("[", "").replace("]", "")
            cited += [c.strip() for c in names.split(",") if c.strip()]
        else:
            body_lines.append(line)
    body = "\n".join(body_lines).strip() or reply.strip()

    # 거절 답변 보호장치: 근거가 없다고 해 놓고 출처를 붙이면 화면에 엉뚱한 "근거"가 보이니까 지워요.
    if body.startswith("제공된 자료에서") and "확인할 수 없" in body:
        body = re.split(r"\s*출처\s*[:：]", body)[0].strip()   # 같은 줄에 붙은 "출처: ..."도 제거
        cited = []
    return body, cited


def make_excerpt(text, limit=120):
    """설명글 앞부분을 잘라 출처 카드용 미리보기를 만들어요. (text에는 머리말이 없어요)"""
    body = re.sub(r"\s+", " ", text).strip()
    return body if len(body) <= limit else body[:limit] + "…"


def answer(question):
    """질문 하나에 대한 전체 RAG 과정을 수행해요.
    돌려주는 값(딕셔너리):
        answer  : LLM 답변 본문 (출처 줄은 뺀 것)
        model   : 실제로 답한 모델 이름
        sources : 검색된 참고 자료 목록. cited=True면 LLM이 출처로 직접 적은 유산이에요.
    예상 가능한 문제는 RagError 계열로 바꿔서 던져요. (main.py가 안내 문구로 바꿔 응답해요.)"""
    try:
        hits = search(question)                                   # ① 검색
        reply, model_used = ask_llm(build_prompt(question, hits))  # ② 프롬프트 조립 + ③ 생성
    except RagError:
        raise                                                      # 이미 이름표가 붙은 오류는 그대로 통과
    except psycopg2.Error as e:                                    # DB 연결/검색 오류
        raise DatabaseError() from e
    except Exception as e:                                         # Gemini 쪽 오류를 종류별로 나눠요.
        msg = str(e)
        if is_daily_quota(msg):
            raise QuotaExceededError() from e
        if is_retryable(msg):
            raise ServiceBusyError() from e
        raise                                                      # 정체를 모르는 오류는 그대로 던져서 로그에 남겨요.

    body, cited = split_answer_and_citations(reply)
    cited_set = set(cited)
    sources = [
        {
            "gung_name": h["gung_name"],
            "name": h["name"],
            "similarity": h["similarity"],
            "img_url": h["img_url"],
            "excerpt": make_excerpt(h["text"]),
            "cited": f"{h['gung_name']} {h['name']}" in cited_set,   # LLM이 출처로 적었는지
        }
        for h in hits
    ]
    return {"answer": body, "model": model_used, "sources": sources}
