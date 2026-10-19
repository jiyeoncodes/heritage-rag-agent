# fixed_pipeline.py
# ------------------------------------------------------------
# "고정 RAG" — Agent와 공정하게 비교하려고 만든 기준선(비교 대상)이에요.
#
#   Agent       : LLM이 "어떤 도구를, 어떤 검색어로, 몇 번" 쓸지 스스로 정해요.
#   고정 RAG(여기): 순서가 정해져 있어요. 질문 그대로
#                   ① 유산 설명 검색 1번 → ② 실록 검색 1번 → ③ LLM 1번 호출로 답변
#                   (검색어 바꾸기·필터·재시도·안전장치 없음)
#
# 공정성을 위해 Agent와 "같게" 둔 것:
#   - 검색 함수  : agent_tools.search_heritage / search_sillok 를 그대로 (결과 모양·글자 수 제한까지 같음)
#   - 답변 규칙  : agent.SYSTEM_INSTRUCTION 의 '답변 규칙' 부분을 그대로 가져다 씀
#   - 모델·재시도: rag.LLM_MODEL, rag._call_with_retry, 예비 모델 전환
#   - 채점       : 출처 표시(cited)·거절 판정을 agent.py 함수로 똑같이
# "다르게" 둔 것은 오직 하나: 흐름을 LLM이 정하느냐(Agent), 코드가 정해 놨느냐(고정 RAG).
#
# 실행 (backend 폴더에서):
#   python fixed_pipeline.py "세종의 능을 옮긴 이유는?"
# ------------------------------------------------------------

import sys

import psycopg2
from google.genai import types

import agent                      # split_answer, SYSTEM_INSTRUCTION(답변 규칙) 재사용
import rag
from agent_tools import search_heritage, search_sillok

# Agent의 SYSTEM_INSTRUCTION에서 '답변 규칙' 부분만 가져와요. (도구 사용 안내는 고정 RAG에 해당 없음)
_RULES = "답변 규칙:" + agent.SYSTEM_INSTRUCTION.split("답변 규칙:", 1)[1]

SYSTEM_INSTRUCTION = """당신은 조선의 궁궐, 종묘, 조선왕릉과 조선왕조실록을 안내하는 해설사입니다.
질문과 함께 '참고 자료'(유산 설명, 실록 기사 요약)가 주어집니다. 참고 자료에 적힌 내용만 근거로 답하세요.
질문과 관련 없는 자료는 쓰지 마세요.

""" + _RULES


def _build_prompt(question, heritage, sillok):
    """질문 + 검색된 자료 전부를 한 덩어리 글로 만들어요. (Agent는 도구 결과를 대화로 받지만, 여기는 한 번에 줘요)"""
    lines = [f"질문: {question}", "", "[유산 설명 자료]"]
    if heritage:
        for i, h in enumerate(heritage, 1):
            lines.append(f"{i}. label: {h['label']}\n   {h['text']}")
    else:
        lines.append("(검색된 자료 없음)")
    lines += ["", "[실록 기사 요약 자료]"]
    if sillok:
        for i, s in enumerate(sillok, 1):
            tomb = f" (능: {s['tomb']})" if s.get("tomb") else ""
            lines.append(f"{i}. label: {s['label']}{tomb}\n   {s['summary']}")
    else:
        lines.append("(검색된 자료 없음)")
    return "\n".join(lines)


def _generate(model, prompt):
    def _call():
        cfg = types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION, temperature=0.2)
        return rag.client.models.generate_content(model=model, contents=prompt, config=cfg)
    return rag._call_with_retry(_call, model)


def _generate_with_fallback(prompt):
    """기본 모델이 실패하면 예비 모델로 한 번 더 (agent와 같은 방식)"""
    try:
        return _generate(rag.LLM_MODEL, prompt), rag.LLM_MODEL
    except Exception as e:
        msg = str(e)
        can = (rag.is_retryable(msg) or rag.is_daily_quota(msg)) and rag.FALLBACK_MODEL \
            and rag.FALLBACK_MODEL != rag.LLM_MODEL
        if not can:
            raise
        print(f"[전환] {rag.LLM_MODEL} 사용 불가 → 예비 모델 {rag.FALLBACK_MODEL}")
        return _generate(rag.FALLBACK_MODEL, prompt), rag.FALLBACK_MODEL


def ask(question):
    """질문 1개를 고정 순서로 처리해요. 돌려주는 모양은 agent.ask()와 같아요(평가 코드를 같이 쓰려고)."""
    try:
        h_res = search_heritage(question)                  # ① 질문 그대로 유산 검색
        s_res = search_sillok(question)                    # ② 질문 그대로 실록 검색 (tomb·reign 필터 없음)
        if not h_res.get("ok") and not s_res.get("ok"):    # 둘 다 실패(DB·한도 문제)면 답할 수 없어요
            raise rag.DatabaseError()
        heritage, sillok = h_res.get("results", []), s_res.get("results", [])
        response, model_used = _generate_with_fallback(_build_prompt(question, heritage, sillok))   # ③ LLM 1번
        reply = (response.text or "").strip()
        if not reply:
            raise rag.LlmError()
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

    body, refused = agent.split_answer(reply)
    sources = heritage + sillok
    for s in sources:                                      # 답변에 쓰인 자료 표시 (agent.ask와 같은 기준)
        keys = [s.get("label"), s.get("date")]
        s["cited"] = (not refused) and any(k and k in body for k in keys)
    steps = [{"tool": "search_heritage", "args": {"query": question}, "n_results": len(heritage)},
             {"tool": "search_sillok", "args": {"query": question}, "n_results": len(sillok)}]
    return {"answer": body, "cited": [s["label"] for s in sources if s["cited"]], "model": model_used,
            "steps": steps, "sources": sources, "guard": None, "retried": False}


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "세종의 능을 옮긴 이유는?"
    out = ask(q)
    print(f"질문: {q}\n\n[답변] ({out['model']})\n{out['answer']}\n\n[출처] {', '.join(out['cited']) or '-'}")
    for s in out["sources"]:
        print(f"  {'●' if s['cited'] else '○'} ({s['kind']}) {s.get('label')}")
