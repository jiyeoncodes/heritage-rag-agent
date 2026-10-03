# eval_answer.py
# ------------------------------------------------------------
# RAG 답변 전체(검색 + LLM)를 여러 질문으로 한 번에 평가하는 스크립트예요.
#
# 두 가지를 동시에 확인해요.
#   A) 정답이 있는 질문: LLM이 정답 유산을 '출처'로 골랐는가?
#   B) 자료에 없는 질문(환각 테스트): LLM이 지어내지 않고 "확인할 수 없다"고 하는가?
#
# ★ 무료 티어는 모델당 '하루 호출 수'가 적어요(예: 20번). 그래서 이 스크립트는
#   - 질문 하나가 끝날 때마다 결과를 CSV에 바로 저장하고,
#   - 다시 실행하면 이미 답한 질문은 건너뛰고(이어하기),
#   - 하루 한도에 걸리면 기다리지 않고 지금까지의 결과를 보여준 뒤 멈춰요.
#
# 사용 방법:
#   python eval_answer.py              # B(환각) → A(정답있음) 순서로 전부
#   python eval_answer.py halluc       # B(환각 테스트)만 - 6번 호출
#   python eval_answer.py hard         # 어려운 질문만(환각 6 + 별칭형 4 = 10번 호출)
#   python eval_answer.py answerable   # A(정답 있는 질문)만
#
# 모델을 바꿔서 비교하고 싶으면 (결과 파일 이름에 모델명이 들어가서 따로 저장돼요):
#   Windows(PowerShell):  $env:LLM_MODEL="gemini-3.1-flash-lite"; python eval_answer.py halluc
#   Mac/Linux:            LLM_MODEL=gemini-3.1-flash-lite python eval_answer.py halluc
# ------------------------------------------------------------

import csv
import re
import sys
import time

import answer_test                              # 앞서 만든 RAG 답변 코드를 재사용해요
from answer_test import answer, is_retryable, is_daily_quota, LLM_MODEL
from eval_search import EVAL_SET                # 검색 평가 때 쓴 15개 질문(정답 포함)을 그대로 재사용해요
from search_test import PROJECT_ROOT

# ▼ 공정한 모델 비교를 위해 "예비 모델 자동 전환"을 꺼요.
#   (전환되면 어떤 모델이 답했는지 섞여서 비교가 의미 없어져요.)
answer_test.FALLBACK_MODEL = answer_test.LLM_MODEL

SLEEP_BETWEEN_QUESTIONS = 4   # 질문 사이 대기(초). 분당 한도를 지키기 위해서예요.
MAX_Q_RETRIES = 3             # 일시적 오류(429 분당한도/503)로 실패한 질문을 다시 시도할 횟수
Q_RETRY_WAIT = 30             # 그때 기다릴 시간(초)

# ------------------------------------------------------------
# 환각 테스트용 질문: 우리 데이터(국가유산청 궁궐·종묘 API)에 "답이 없는" 질문들이에요.
# 정답은 하나, "확인할 수 없다"고 답하는 것!
#   - 경희궁, 조선 왕릉은 아직 수집하지 않은 '알려진 데이터 공백'이에요.
# ------------------------------------------------------------
HALLUC_SET = [
    "경복궁에 놀이공원이 있어?",
    "경복궁의 입장료는 얼마야?",
    "창덕궁 주차장은 어디에 있어?",
    "경희궁은 언제 지어졌어?",                 # 데이터 공백(경희궁 미수집)
    "조선 왕릉 중 가장 큰 능은 어디야?",        # 데이터 공백(왕릉 미수집)
    "세종대왕릉(영릉)은 어디에 있어?",          # 데이터 공백(왕릉 미수집)
]

# 답변에 이 표현이 있으면 "모른다고 했다"로 자동 판정해요. (LLM에게 알려준 문구: "확인할 수 없습니다")
REFUSAL_WORDS = ["확인할 수 없", "알 수 없", "나와 있지 않", "찾을 수 없", "언급되어 있지 않", "제공된 자료에는"]

# 결과 CSV 위치 (모델마다 파일이 따로 생겨요)
OUT_DIR = PROJECT_ROOT / "data" / "eval"
OUT_PATH = OUT_DIR / f"answer_eval_{re.sub(r'[^A-Za-z0-9._-]', '_', LLM_MODEL)}.csv"
FIELDS = ["group", "type", "question", "expected", "retrieved", "in_source", "in_text", "refused", "reply"]
BOOL_FIELDS = ["retrieved", "in_source", "in_text", "refused"]


def load_done():
    """이전에 저장된 결과가 있으면 읽어서 {(그룹, 질문): 행} 딕셔너리로 돌려줘요. (이어하기용)"""
    done = {}
    if OUT_PATH.exists():
        with open(OUT_PATH, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                for k in BOOL_FIELDS:                       # CSV에서는 "True"/"False" 글자라서 다시 참/거짓으로 바꿔요
                    r[k] = True if r[k] == "True" else (False if r[k] == "False" else r[k])
                if r["reply"]:
                    done[(r["group"], r["question"])] = r
    return done


def save_rows(rows):
    """지금까지의 결과 전체를 CSV에 저장해요. 질문 하나 끝날 때마다 부르면, 중간에 멈춰도 결과가 안 날아가요."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def run_one(question):
    """질문 1개를 RAG로 답하게 해요. 분당 한도(429)/서버 바쁨(503)이면 잠깐 쉬었다 다시 시도해요.
    하루 한도(PerDay)는 재시도해도 소용없어서, 그대로 오류를 던져 위에서 멈추게 해요."""
    for attempt in range(1, MAX_Q_RETRIES + 1):
        try:
            return answer(question)               # (답변 텍스트, 검색 결과 hits)
        except Exception as e:
            if not is_retryable(str(e)) or attempt == MAX_Q_RETRIES:
                raise
            print(f"    ! 일시적 오류. {Q_RETRY_WAIT}초 후 재시도... ({attempt}/{MAX_Q_RETRIES})")
            time.sleep(Q_RETRY_WAIT)


def get_source_line(reply):
    """답변에서 '출처: ...' 줄만 뽑아요. 없으면 빈 문자열."""
    for line in reply.splitlines():
        if line.strip().startswith("출처"):
            return line
    return ""


def one_line(text, n=60):
    """표에 넣기 좋게 줄바꿈을 없애고 n글자로 자르는 함수예요."""
    return re.sub(r"\s+", " ", text).strip()[:n]


def build_tasks(mode):
    """이번에 처리할 질문 목록을 (그룹, 유형, 질문, 정답궁, 정답유산) 형태로 만들어요. 환각 테스트를 먼저 해요."""
    halluc = [("환각테스트", "자료없음", q, None, None) for q in HALLUC_SET]
    answerable = [("정답있음", t, q, g, n) for q, g, n, t in EVAL_SET]
    if mode == "halluc":
        return halluc
    if mode == "answerable":
        return answerable
    if mode == "hard":
        return halluc + [x for x in answerable if x[1] == "별칭형"]
    return halluc + answerable          # all


def evaluate(task, reply, hits):
    """답변 1개를 채점해서 CSV 한 줄(딕셔너리)로 만들어요."""
    group, qtype, q, gung, name = task
    refused = any(w in reply for w in REFUSAL_WORDS)
    if group == "환각테스트":
        return {"group": group, "type": qtype, "question": q, "expected": "(모른다고 답해야 함)",
                "retrieved": "", "in_source": "", "in_text": "", "refused": refused, "reply": reply}
    source = get_source_line(reply)
    return {"group": group, "type": qtype, "question": q, "expected": f"{gung} {name}",
            "retrieved": any(g == gung and n == name for g, n, _t, _s in hits),   # 검색에서 정답을 가져왔나?
            "in_source": f"{gung} {name}" in source,                               # 정답을 출처로 골랐나? (엄격)
            "in_text": name in reply,                                              # 정답 이름이 답변에 있나? (느슨)
            "refused": refused, "reply": reply}


def print_report(rows):
    """모인 결과를 표와 요약으로 보여줘요."""
    ans = [r for r in rows if r["group"] == "정답있음"]
    hal = [r for r in rows if r["group"] == "환각테스트"]

    if ans:
        print("\n" + "=" * 90)
        print("A) 정답이 있는 질문   (검색=정답을 검색에서 가져왔나 / 출처=정답을 출처로 골랐나)")
        print("-" * 90)
        for r in ans:
            print(f"[{r['type']}] {r['question']}  → 정답 {r['expected']}")
            print(f"    검색 {'O' if r['retrieved'] else 'X'} | 출처 {'O' if r['in_source'] else 'X'} | 답변: {one_line(r['reply'])}")
        n = len(ans)
        print(f"\n  검색 단계 적중 {sum(1 for r in ans if r['retrieved'])}/{n}   "
              f"LLM이 출처로 정답 선택 {sum(1 for r in ans if r['in_source'])}/{n}   "
              f"(정답 이름이 답변에 등장 {sum(1 for r in ans if r['in_text'])}/{n})")
        for t in ["이름형", "설명형", "별칭형"]:
            sub = [r for r in ans if r["type"] == t]
            if sub:
                print(f"    {t}: 출처 정답 {sum(1 for r in sub if r['in_source'])}/{len(sub)}")

    if hal:
        print("\n" + "=" * 90)
        print("B) 환각 테스트   (자동판정: '모른다/확인할 수 없다' 표현이 있으면 O) ← 반드시 답변을 직접 읽어서 확인하세요!")
        print("-" * 90)
        for r in hal:
            print(f"[{'O 거절' if r['refused'] else 'X 답함'}] {r['question']}")
            print(f"    답변: {one_line(r['reply'], 200)}")
        print(f"\n  모른다고 답한 질문 {sum(1 for r in hal if r['refused'])}/{len(hal)}")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    tasks = build_tasks(mode)
    done = load_done()                 # 이전에 이미 끝낸 질문들
    rows = []
    stopped_by_quota = False
    new_calls = 0

    print(f"모델: {LLM_MODEL} | 모드: {mode} | 질문 {len(tasks)}개 (이미 저장된 {sum(1 for t in tasks if (t[0], t[2]) in done)}개는 건너뜀)")

    for i, task in enumerate(tasks, start=1):
        key = (task[0], task[2])
        if key in done:                          # 이미 답한 질문은 저장된 결과를 그대로 써요
            rows.append(done[key])
            continue
        print(f"[{i}/{len(tasks)}] ({task[0]}) {task[2]}")
        try:
            reply, hits = run_one(task[2])
        except Exception as e:
            if is_daily_quota(str(e)):           # 하루 한도: 더 시도해도 소용없으니 여기서 멈춰요
                stopped_by_quota = True
                print(f"\n!!! {LLM_MODEL}의 '하루 무료 한도'에 도달했어요. 지금까지 결과만 정리하고 멈춥니다.")
                break
            raise                                # 그 밖의 오류(모델 이름 오류 등)는 그대로 보여줘요
        rows.append(evaluate(task, reply, hits))
        new_calls += 1
        # 지금까지 결과를 '이번에 처리 안 한 질문의 저장본'과 합쳐서 바로 저장해요.
        save_rows(rows + [v for k, v in done.items() if k not in {(r["group"], r["question"]) for r in rows}])
        time.sleep(SLEEP_BETWEEN_QUESTIONS)

    if rows:
        print_report(rows)

    remaining = len(tasks) - len(rows)
    print(f"\n이번 실행에서 새로 호출한 횟수: {new_calls}번 | 저장 위치: {OUT_PATH}")
    if stopped_by_quota or remaining:
        print(f"아직 못 한 질문 {remaining}개 → 하루 한도가 초기화된 뒤(또는 다른 모델로) 같은 명령을 다시 실행하면 이어서 해요.")


if __name__ == "__main__":
    main()
