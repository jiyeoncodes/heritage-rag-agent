# agent.py
# ------------------------------------------------------------
# 질문에 따라 LLM이 직접 도구를 골라 쓰는 Agent예요. (2단계)
#
#   기존 rag.answer():  질문 → (항상) 유산 검색 → 답변          ← 순서가 고정된 RAG
#   이 agent.ask():     질문 → LLM이 "어떤 도구를 부를지" 결정 → 도구 실행 → 결과를 보고
#                       "더 찾아볼지/답할지" 다시 결정 → ... → 최종 답변   ← LLM이 흐름을 정하는 Agent
#
# 반복 구조(루프):
#   1) LLM에게 질문 + 도구 목록을 준다
#   2) LLM이 "도구 호출"을 요청하면 → 우리가 실제로 실행해서 결과를 돌려준다 → 1)로 돌아감
#   3) LLM이 도구 호출 없이 글을 쓰면 → 그게 최종 답변이다
#   (무한 반복을 막으려고 최대 MAX_STEPS번까지만 돌아요)
#
# 실행 (backend 폴더에서):
#   python agent.py "세종의 능을 옮긴 이유는?"
# ------------------------------------------------------------

import re
import sys

import psycopg2
from google.genai import types

import rag                       # LLM 클라이언트, 모델 이름, 재시도·오류 처리 재사용
from agent_tools import TOOLS

MAX_STEPS = 5                    # 도구 호출 왕복 최대 횟수 (무료 한도와 시간을 지키기 위한 안전장치)

SYSTEM_INSTRUCTION = """당신은 조선의 궁궐, 종묘, 조선왕릉과 조선왕조실록을 안내하는 해설사입니다.
질문에 맞는 도구를 직접 골라 사용하고, 도구가 돌려준 내용만 근거로 답하세요.

도구 사용 방법:
- 건물·문·능의 위치, 구조, 특징 같은 '현재 유산 설명' → search_heritage
- 과거에 있었던 사건, 인물의 행적, 능의 이전(천장·천릉)·제사·수리 같은 '역사 기록' → search_sillok
- 사용자가 '세종의 능'처럼 인물로 말하면, 먼저 find_tomb_names로 정확한 능 이름(예: 영릉(세종))을 확인한 뒤 search_sillok의 tomb에 넣으세요.
- search_sillok의 검색어는 질문 문장 그대로가 아니라 실록에서 쓰는 말(천장, 천릉, 친제 등)로 바꿔 쓰세요.
- 결과가 부족하면 검색어나 필터를 바꿔 한두 번 더 찾아보세요. 두 종류의 자료가 모두 필요하면 두 도구를 모두 쓰세요.
- find_tomb_names 결과에 같은 이름의 능이 여럿(예: 영릉(세종), 영릉(효종))이고 질문이 어느 쪽인지 분명하지 않으면,
  후보마다 search_sillok을 따로 호출하거나, 답변에서 어느 능의 기록인지 구분해 밝히세요. 임의로 하나만 고르지 마세요.
- 이 서비스의 주제(궁궐·종묘·왕릉과 관련 실록 기록)에 관한 질문이면, 도구를 한 번도 쓰지 않고 "확인할 수 없다"고 답하지 마세요.
  반드시 한 번 이상 검색한 뒤 판단하세요. 인사나 주제와 무관한 질문만 도구 없이 짧게 안내해도 됩니다.

답변 규칙:
1. 도구 결과에 근거가 없으면 지어내지 말고 "제공된 자료에서는 확인할 수 없습니다."라고 답하세요.
2. 쉬운 한국어로 3~6문장 이내로 간결하게 쓰세요. 추론한 내용은 "자료상 ~로 보입니다"처럼 추론임을 드러내세요.
3. 자료를 근거로 쓸 때마다 그 문장 바로 뒤에 괄호로 근거를 밝히세요.
   실록은 날짜만 적고 → (세종실록 28년 7월 20일), 유산 설명은 label 전체를 적습니다 → (조선왕릉 여주 영릉과 영릉).
   본문에서 실제로 사용한 자료만 괄호로 밝히고, 사용하지 않은 자료는 어디에도 쓰지 마세요.
   실록 결과는 AI가 만든 한글 요약이라, 요약에 없는 세부 내용은 단정하지 마세요.
   또 제목이나 요약에 그 능이 선례·비교로만 언급된 기사는 그 능의 기록처럼 쓰지 마세요.
4. 질문이 '이유·원인'을 묻는데 자료에 이유가 직접 적혀 있지 않으면, 먼저 "직접적인 이유는 제공된 자료에서 확인되지 않습니다."라고 밝히고,
   자료에서 확인되는 관련 사실(누가 언제 무엇을 논의했는지 등)만 덧붙이세요. 관련 사실을 이유처럼 말하지 마세요.
5. 답변 맨 끝에 한 줄로 '출처: 이름1, 이름2'를 적되, 본문에서 괄호로 밝힌 자료만 label 전체로 쓰세요.
   근거가 없어 답하지 못할 때는 출처 줄을 쓰지 마세요."""


def _generate(model, contents, use_tools):
    """모델 1개로 LLM을 한 번 호출해요. use_tools=False면 도구 없이 '글로만 답하라'고 해요."""
    def _call():
        cfg = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.2,
            tools=list(TOOLS.values()) if use_tools else None,        # 파이썬 함수를 그대로 도구로 등록 (설명은 독스트링에서 읽어요)
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),   # 자동 실행 끔 → 우리가 직접 실행하고 기록
        )
        return rag.client.models.generate_content(model=model, contents=contents, config=cfg)
    return rag._call_with_retry(_call, model)


def _generate_with_fallback(contents, use_tools):
    """기본 모델이 일시적 오류·하루 한도로 실패하면 예비 모델로 한 번 더 시도해요. (rag.ask_llm과 같은 방식)"""
    try:
        return _generate(rag.LLM_MODEL, contents, use_tools), rag.LLM_MODEL
    except Exception as e:
        msg = str(e)
        can_fallback = (rag.is_retryable(msg) or rag.is_daily_quota(msg)) and rag.FALLBACK_MODEL \
            and rag.FALLBACK_MODEL != rag.LLM_MODEL
        if not can_fallback:
            raise
        print(f"[전환] {rag.LLM_MODEL} 사용 불가 → 예비 모델 {rag.FALLBACK_MODEL}")
        return _generate(rag.FALLBACK_MODEL, contents, use_tools), rag.FALLBACK_MODEL


def _run_tool(name, args):
    """LLM이 요청한 도구를 실제로 실행해요. 모르는 이름이면 오류 내용을 LLM에게 돌려줘요."""
    fn = TOOLS.get(name)
    if fn is None:
        return {"ok": False, "error": f"없는 도구입니다: {name}. 사용 가능: {', '.join(TOOLS)}"}
    try:
        return fn(**args)
    except TypeError as e:                                     # 인자 이름·개수가 틀린 경우
        return {"ok": False, "error": f"인자가 잘못되었습니다: {e}"}


def is_refusal(text):
    """거절 답변인지 판단해요. 첫 두 문장 안에 '확인할 수 없'이 있으면 거절로 봐요.
    (예: "경복궁 입장료는 제공된 자료에서 확인할 수 없습니다." 처럼 문장 앞부분이 달라도 잡아요)"""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    head = " ".join(sentences[:2])
    return bool(re.search(r"확인(할|해 드릴) 수 없|(안내|답변)해 드릴 수 없", head))


def split_answer(reply):
    """답변에서 '맨 끝의 출처 줄'만 떼어 내요. (rag의 함수는 본문 중간 '(출처: …)'까지 잘라 문장이 깨졌어요)
    돌려주는 값: (본문, 거절 답변인지)"""
    lines = reply.strip().splitlines()
    last = None
    for i, line in enumerate(lines):                       # 줄 맨 앞이 '출처:' 또는 '[출처]'로 시작하는 마지막 줄
        if re.match(r"\s*(\[출처\]|출처\s*[:：])", line):             # "출처: …" 또는 "[출처] …" 로 시작하는 줄
            last = i
    if last is not None:
        kept = lines[:last]
    else:                                                  # 출처가 마지막 문장 끝에 붙어 있는 경우: 그 줄의 '출처:' 이후만 자름
        kept = list(lines)
        if kept:
            kept[-1] = re.split(r"\s+출처\s*[:：]", kept[-1])[0]
    body = "\n".join(kept).strip() or reply.strip()
    refused = is_refusal(body)
    if refused:                                            # 거절 답변: 같은 줄에 붙은 출처도 지워요
        body = re.split(r"\s*출처\s*[:：]", body)[0].strip()
    return body, refused


def ask(question):
    """질문 1개를 Agent로 처리해요.
    돌려주는 값(딕셔너리):
        answer : 최종 답변 본문 (출처 줄 제외)
        cited  : 답변 끝 '출처:' 줄에 적힌 이름들
        model  : 실제로 답한 모델
        steps  : 도구 호출 기록 [{tool, args, n_results}] — Agent가 무엇을 했는지 보여 주는 로그
        sources: 도구가 찾아온 자료 목록 (중복 제거)
    예상 가능한 문제는 rag.RagError 계열로 바꿔 던져요."""
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=question)])]
    steps, sources, seen = [], [], set()
    model_used = rag.LLM_MODEL

    try:
        for step in range(MAX_STEPS + 1):
            last = step == MAX_STEPS                           # 마지막 차례에는 도구를 끄고 지금까지 찾은 걸로 답하게 해요
            response, model_used = _generate_with_fallback(contents, use_tools=not last)
            calls = [] if last else (response.function_calls or [])
            if not calls:                                      # 도구 호출이 없다 = 최종 답변
                reply = (response.text or "").strip()
                if not reply:
                    raise rag.LlmError()
                break

            contents.append(response.candidates[0].content)    # 모델의 요청을 대화 기록에 그대로 덧붙여요 (사고 서명 등 보존)
            result_parts = []
            for call in calls:
                args = dict(call.args or {})
                result = _run_tool(call.name, args)
                steps.append({"tool": call.name, "args": args, "n_results": len(result.get("results", []))})
                for item in result.get("results", []):         # 화면에 보여 줄 출처 목록 수집 (중복 제거)
                    key = (item.get("kind"), item.get("label") or item.get("name"))
                    if item.get("kind") and key not in seen:
                        seen.add(key)
                        sources.append(item)
                result_parts.append(types.Part.from_function_response(name=call.name, response=result))
            contents.append(types.Content(role="user", parts=result_parts))   # 도구 결과를 LLM에게 돌려줘요
    except rag.RagError:
        raise
    except psycopg2.Error as e:
        raise rag.DatabaseError() from e
    except Exception as e:
        msg = str(e)
        if rag.is_daily_quota(msg):
            raise rag.QuotaExceededError() from e
        if rag.is_retryable(msg):
            raise rag.ServiceBusyError() from e
        raise

    body, refused = split_answer(reply)
    match_text = body                                      # 본문에서만 확인 (모델이 출처 줄에 쓰지 않은 자료까지 적는 일이 있어서)
    for s in sources:                                      # 자료마다 '답변에 쓰였는지' 표시 (이름 전체 또는 실록 날짜가 나오면 true)
        keys = [s.get("label"), s.get("date")]
        s["cited"] = (not refused) and any(k and k in match_text for k in keys)   # 거절 답변이면 모두 false
    cited = [s["label"] for s in sources if s["cited"]]    # 출처 목록은 글자 파싱 대신 위 표시에서 만들어요
    return {"answer": body, "cited": cited, "model": model_used, "steps": steps, "sources": sources}


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "세종의 능을 옮긴 이유는?"
    out = ask(q)
    print(f"질문: {q}\n")
    print("[Agent가 한 일]")
    for i, s in enumerate(out["steps"], 1):
        print(f"  {i}. {s['tool']}({s['args']}) -> {s['n_results']}건")
    print(f"\n[답변] ({out['model']})\n{out['answer']}\n")
    print("[출처]", ", ".join(out["cited"]) or "-")
    print("\n[Agent가 찾아온 자료]")                          # 답이 빈약할 때: 자료가 없었는지, 자료는 있는데 못 썼는지 구분용
    for s in out["sources"]:
        print(f"  {'●' if s.get('cited') else '○'} ({s['kind']}) {s.get('label')}")   # ● = 답변에 쓰임
        if s["kind"] == "sillok":
            print(f"        {s['summary'][:90]}…")                                 # 요약 앞부분 (답변이 맞는지 직접 대조용)
