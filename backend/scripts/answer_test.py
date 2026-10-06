# answer_test.py
# ------------------------------------------------------------
# RAG의 전체 흐름을 처음으로 끝까지 연결해 보는 스크립트예요.
#   질문 → (검색) 비슷한 유산 5개 → (생성) LLM이 그 글만 보고 답변 → 출처 표시
#
# 사용 방법:
#   python answer_test.py                          # 기본 질문
#   python answer_test.py "경복궁의 정문은 어디야?"   # 질문 직접 입력
# ------------------------------------------------------------

import os
import re
import sys
import time
from pathlib import Path
from google import genai
from google.genai.types import GenerateContentConfig

# 이미 만들어 둔 검색 함수와 환경설정을 재사용해요. (같은 scripts/ 폴더에 있어야 해요)
from search_test import client   # client = Gemini 클라이언트(.env의 키로 이미 만들어져 있음)

# 검색은 실제 서비스(rag.py)와 같은 "하이브리드 검색"을 써요. (예전에는 벡터만 쓰는 search_test.search를 썼어요)
# → 이 스크립트와 eval_answer.py의 결과가 실제 서비스 품질을 반영해요.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))    # backend/ (rag.py가 있는 곳)
import rag


def search(question, top_k=5):
    """rag.search 결과(딕셔너리)를 이 파일이 쓰던 모양 (궁, 유산명, 본문, 유사도) 튜플 리스트로 바꿔 줘요."""
    # DB에는 머리말 없는 원문이 있으니, LLM에게 줄 글은 여기서 "[분류] 유산명 - 원문"으로 조립해요. (rag.build_prompt와 같은 모양)
    return [(h["gung_name"], h["name"], f"[{h['gung_name']}] {h['name']} - {h['text']}", h["similarity"])
            for h in rag.search(question, top_k)]

# ⚠ LLM 모델 이름은 아직 "미정"이라서 상수로 빼 뒀어요. 나중에 평가해서 바꾸기 쉬워요.
#   (무료 티어에서 쓸 수 있는 Gemini Flash 계열 이름으로 바꿔도 돼요. 아래는 예시값이에요.)
LLM_MODEL = os.environ.get("LLM_MODEL", "gemini-3.5-flash-lite")
TOP_K = 5            # LLM에게 보여줄 참고 자료 개수 (검색 결과 상위 몇 개)
# 예비 모델: 기본 모델이 계속 실패(503 등)하면 자동으로 이 모델로 바꿔서 다시 시도해요.
FALLBACK_MODEL = os.environ.get("LLM_FALLBACK_MODEL", "gemini-3.1-flash-lite")
MAX_RETRIES = 4      # 모델 1개당 재시도 횟수
RETRY_WAIT = 30      # 429일 때 서버가 대기시간을 안 알려주면 쓸 기본 대기(초)
BACKOFF_BASE = 5     # 503일 때 첫 대기(초). 5초 → 10초 → 20초 → 40초로 두 배씩 늘어나요.

# LLM에게 주는 "역할 + 규칙" 설명서예요. RAG에서 가장 중요한 부분이에요.
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


def build_prompt(question, hits):
    """검색 결과(hits)를 '참고 자료' 문자열로 이어 붙이고, 질문과 합쳐 LLM에게 줄 프롬프트를 만들어요."""
    # hits의 각 원소: (궁 이름, 유산명, 본문, 유사도)
    blocks = []
    for i, (gung, name, text, _sim) in enumerate(hits, start=1):
        # 본문 맨 앞에는 이미 "[궁] 유산명 - "이 붙어 있어서, 그대로 번호만 붙여요.
        blocks.append(f"({i}) {text}")
    reference = "\n\n".join(blocks)
    return f"[참고 자료]\n{reference}\n\n[질문]\n{question}"


def is_daily_quota(msg):
    """'하루 사용량 한도'에 걸린 오류인지 판단해요. (메시지에 PerDay가 들어 있어요.)
    이 경우는 1분을 기다려도 안 풀려요. 다음 날 초기화될 때까지 기다려야 해요."""
    return "PerDay" in msg


def is_retryable(msg):
    """'잠깐 기다리면 풀릴 수 있는 오류'인지 판단해요.
    429(분당 한도) / 503(서버가 일시적으로 바쁨)은 재시도해요.
    하루 한도(PerDay)와 404(모델 이름 오류)는 기다려도 안 풀리니까 재시도하지 않아요."""
    if is_daily_quota(msg):
        return False
    return any(k in msg for k in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE"))


def call_model(model, prompt):
    """모델 1개로 LLM을 호출하고, 일시적 오류면 기다렸다 다시 시도해요. 끝까지 실패하면 오류를 그대로 던져요."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.2,   # 낮을수록 "지어내기"가 줄고 답이 일정해져요. 사실 기반 답변엔 낮게!
                ),
            )
            return response.text
        except Exception as e:
            msg = str(e)
            if not is_retryable(msg) or attempt == MAX_RETRIES:
                raise
            found = re.search(r"retry in ([\d.]+)s", msg)   # 서버가 "13초 뒤에 다시"라고 알려주면 그 시간만큼
            wait = float(found.group(1)) + 2 if found else BACKOFF_BASE * (2 ** (attempt - 1))
            print(f"    ! 일시적 오류({model}). {wait:.0f}초 후 재시도... ({attempt}/{MAX_RETRIES})")
            time.sleep(wait)


def ask_llm(prompt):
    """기본 모델로 시도하고, 계속 실패하면 예비 모델로 바꿔서 한 번 더 시도해요."""
    try:
        return call_model(LLM_MODEL, prompt)
    except Exception as e:
        # 모델 이름 오류(404) 등은 예비 모델로 가지 않고 바로 알려줘요.
        # 하루 한도(PerDay)는 '모델별'로 따로 세기 때문에, 예비 모델로 바꾸면 계속 쓸 수 있어요.
        msg = str(e)
        if not (is_retryable(msg) or is_daily_quota(msg)) or FALLBACK_MODEL == LLM_MODEL:
            raise
        print(f"    ! {LLM_MODEL} 사용 불가 → 예비 모델 {FALLBACK_MODEL}로 전환해요.")
        return call_model(FALLBACK_MODEL, prompt)


def answer(question):
    """질문 하나에 대한 전체 RAG 과정을 수행하고 (답변, 사용한 참고 자료)를 돌려줘요."""
    hits = search(question, top_k=TOP_K)      # ① 검색
    prompt = build_prompt(question, hits)      # ② 프롬프트 조립
    return ask_llm(prompt), hits               # ③ 생성


if __name__ == "__main__":
    question = sys.argv[1] if len(sys.argv) > 1 else "경복궁의 정문은 어디야?"
    reply, hits = answer(question)

    print(f"질문: {question}\n")
    print("=== LLM 답변 ===")
    print(reply)
    print("\n=== LLM에게 보여준 참고 자료 (검색 순위순) ===")
    for rank, (gung, name, _text, sim) in enumerate(hits, start=1):
        print(f"  {rank}위  {gung} {name}  (유사도 {sim:.3f})")
