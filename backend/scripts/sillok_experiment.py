# sillok_experiment.py
# ------------------------------------------------------------
# 실록 기사 20건으로 "한문을 어떻게 임베딩할까?"를 비교하는 실험 스크립트입니다.
#
#   방법 ① 한문 그대로 임베딩   : 제목(한글) + 한문 본문 앞부분을 그대로 벡터로 변환
#   방법 ③ 한국어 요약 후 임베딩 : LLM이 한문을 읽고 한국어 요약을 만듦 → 제목 + 요약을 벡터로 변환
#
# 비교 방법 (eval_search.py와 같은 아이디어):
#   기사마다 "한국어 질문" 1개를 LLM이 만들어요 (정답 = 그 기사).
#   질문을 벡터로 바꿔서 20개 기사 중 정답 기사가 몇 등으로 나오는지 ①과 ③을 비교해요.
#   → 1등 비율(Top-1)과 평균 역순위(MRR, 1등=1.0 / 2등=0.5 / 3등=0.33 ...)
#
# DB는 쓰지 않아요 (메모리에서 계산). 그래서 DB에 아무 영향이 없어요.
# 호출 횟수: LLM 20번(요약+질문을 한 번에) + 임베딩 3묶음(한문 20 + 요약 20 + 질문 20)
#
# 한도(429)에 걸려 멈춰도 다시 실행하면 이어서 해요. (중간 결과를 캐시 파일에 저장)
#
# 실행 방법 (backend/scripts 폴더에서):
#   python sillok_experiment.py            # 20건 (기본)
#   python sillok_experiment.py --n 10     # 건수 바꾸기
#   python sillok_experiment.py --reset    # 캐시를 지우고 처음부터
#
# 결과 파일 (backend/data/eval/):
#   sillok_experiment_cache.json    : 중간 저장 (요약·질문·벡터)
#   sillok_experiment_result.csv    : 기사별 순위 + 요약 + 질문 (직접 읽어서 요약 품질을 확인하세요!)
#
# ※ 한계: 질문도 LLM이 만들기 때문에 ③(LLM 요약)에 유리하게 나올 수 있어요.
#   결과 CSV의 'question' 열을 직접 고친 뒤 --rescore 로 다시 채점하면 더 공정해요.
# ------------------------------------------------------------

import argparse
import json
import os
import re
import time
from pathlib import Path

import numpy as np                      # 벡터 계산(코사인 유사도)용
import pandas as pd
from dotenv import load_dotenv
from google import genai
from google.genai.types import EmbedContentConfig, GenerateContentConfig

# ---------------- 경로 / 설정 ----------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent                              # backend/
CSV_PATH = PROJECT_ROOT / "data" / "processed" / "sillok_heritage_articles_clean.csv"
EVAL_DIR = PROJECT_ROOT / "data" / "eval"
CACHE_PATH = EVAL_DIR / "sillok_experiment_cache.json"
RESULT_PATH = EVAL_DIR / "sillok_experiment_result.csv"

load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=True)
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

LLM_MODEL = os.environ.get("LLM_MODEL", "gemini-3.5-flash-lite")
FALLBACK_MODEL = os.environ.get("LLM_FALLBACK_MODEL", "gemini-3.1-flash-lite")
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768

HANJA_MAX = 1500        # ①에서 임베딩할 한문 본문 길이(글자). 너무 길면 앞부분만 써요.
SUMMARY_INPUT_MAX = 6000  # ③에서 LLM에게 보여줄 본문 최대 길이
SEED = 42               # 같은 기사가 매번 뽑히도록 고정
MAX_RETRIES = 5
SLEEP = 4               # LLM 호출 사이 대기(초): 분당 한도 보호

PROMPT = """당신은 조선왕조실록 전문가입니다. 아래는 실록 기사 하나입니다. (한문 원문)
다음 두 가지를 만들어 JSON으로만 답하세요.

1. summary: 한국어 요약 (3~5문장). 누가, 언제, 어디서, 무엇을 했는지 포함. 인명·지명·능·궁궐 이름은 한글로 쓰고
   처음 나올 때 한자를 괄호로 덧붙이세요. 원문에 없는 내용은 절대 추가하지 마세요.
2. question: 이 기사를 찾으려는 사용자가 물을 법한 한국어 질문 1개.
   기사 제목을 그대로 베끼지 말고, 일반 사용자의 말투로 쓰세요. (예: "단종의 무덤은 어떻게 만들어졌어?")

출력 형식: {{"summary": "...", "question": "..."}}

[제목] {title}
[본문]
{text}
"""


# ---------------- 도우미 함수 ----------------
def retry(fn, what):
    """429/503이면 기다렸다 재시도. 하루 한도(PerDay)면 바로 멈추고 안내해요."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn()
        except Exception as e:
            msg = str(e)
            if "PerDay" in msg:
                raise SystemExit(f"\n하루 한도에 걸렸어요 ({what}). 내일 다시 실행하면 이어서 해요.")
            retryable = any(k in msg for k in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE"))
            if not retryable or attempt == MAX_RETRIES:
                raise
            found = re.search(r"retry in ([\d.]+)s", msg)
            wait = float(found.group(1)) + 2 if found else 30 * attempt
            print(f"    ! 일시적 오류({what}). {wait:.0f}초 후 재시도 ({attempt}/{MAX_RETRIES})")
            time.sleep(wait)


def ask_llm(prompt):
    """JSON으로 답을 받아요. 기본 모델이 안 되면 예비 모델로 한 번 바꿔요."""
    def call(model):
        r = client.models.generate_content(
            model=model, contents=prompt,
            config=GenerateContentConfig(temperature=0.2, response_mime_type="application/json"))
        return r.text
    try:
        return retry(lambda: call(LLM_MODEL), LLM_MODEL)
    except SystemExit:
        raise
    except Exception as e:
        print(f"    ! {LLM_MODEL} 실패({str(e)[:80]}) → {FALLBACK_MODEL}로 전환")
        return retry(lambda: call(FALLBACK_MODEL), FALLBACK_MODEL)


def embed(texts, task_type):
    """글 여러 개를 임베딩해서 숫자 리스트들로 돌려줘요. (10개씩 묶어서 호출)"""
    out = []
    for i in range(0, len(texts), 10):
        batch = texts[i:i + 10]
        res = retry(lambda: client.models.embed_content(
            model=EMBEDDING_MODEL, contents=batch,
            config=EmbedContentConfig(task_type=task_type, output_dimensionality=EMBEDDING_DIM)), "embedding")
        out += [e.values for e in res.embeddings]
        time.sleep(SLEEP)
    return out


def pick_articles(n):
    """실험할 기사 n개를 고정된 방식으로 뽑아요. 너무 짧거나 너무 긴 기사는 제외."""
    df = pd.read_csv(CSV_PATH)
    df = df[(df["language"] == "hanja") & df["text_length"].between(150, 2500)]
    return df.sample(n=n, random_state=SEED).reset_index(drop=True)


def rank_of(sim_row, correct_idx):
    """유사도 점수 배열에서 정답이 몇 등인지(1등=1)."""
    return int((sim_row > sim_row[correct_idx]).sum()) + 1


def score(q_vecs, d_vecs):
    """질문 벡터들 x 문서 벡터들 코사인 유사도 → 질문 i의 정답은 문서 i."""
    q = np.array(q_vecs); d = np.array(d_vecs)
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    sims = q @ d.T
    return [rank_of(sims[i], i) for i in range(len(q))]


def summarize(ranks, label):
    top1 = sum(r == 1 for r in ranks) / len(ranks)
    top3 = sum(r <= 3 for r in ranks) / len(ranks)
    mrr = sum(1 / r for r in ranks) / len(ranks)
    print(f"  {label:<24} Top-1 {top1:5.0%}   Top-3 {top3:5.0%}   MRR {mrr:.2f}")


# ---------------- 메인 ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--reset", action="store_true", help="캐시 삭제 후 처음부터")
    ap.add_argument("--rescore", action="store_true",
                    help="결과 CSV의 question 열(직접 고친 질문)로 다시 채점 (요약·문서 벡터는 캐시 사용)")
    args = ap.parse_args()

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    if args.reset and CACHE_PATH.exists():
        CACHE_PATH.unlink()
    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}

    def save():
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    arts = pick_articles(args.n)
    ids = list(arts["article_id"])
    print(f"실험 기사 {len(ids)}건 (원문 보관 CSV는 건드리지 않아요)")

    # 1) 기사마다 LLM으로 한국어 요약 + 질문 만들기 (캐시에 있으면 건너뜀)
    cache.setdefault("llm", {})
    todo = [i for i in ids if i not in cache["llm"]]
    print(f"[1/3] LLM 요약+질문: 새로 {len(todo)}건 (캐시 {len(ids) - len(todo)}건)")
    for k, aid in enumerate(todo, 1):
        row = arts[arts["article_id"] == aid].iloc[0]
        raw = ask_llm(PROMPT.format(title=row["title"], text=row["text"][:SUMMARY_INPUT_MAX]))
        try:
            data = json.loads(raw)
            cache["llm"][aid] = {"summary": data["summary"].strip(), "question": data["question"].strip()}
        except Exception:
            print(f"    ! {aid}: JSON 해석 실패, 건너뜀 → 다시 실행하면 재시도해요")
            continue
        save()
        print(f"  ({k}/{len(todo)}) {row['title'][:30]}")
        time.sleep(SLEEP)
    ids = [i for i in ids if i in cache["llm"]]
    arts = arts[arts["article_id"].isin(ids)].reset_index(drop=True)

    # --rescore: 사용자가 CSV에서 고친 질문을 읽어 캐시에 반영 (그 질문만 다시 임베딩)
    if args.rescore and RESULT_PATH.exists():
        edited = pd.read_csv(RESULT_PATH).set_index("article_id")["question"].to_dict()
        for aid in ids:
            if edited.get(aid) and edited[aid] != cache["llm"][aid]["question"]:
                cache["llm"][aid]["question"] = edited[aid]
                cache.get("q_vec", {}).pop(aid, None)
        save()

    # 2) 두 가지 문서 글을 만들어서 임베딩 (제목은 한글이라 두 방법 모두 포함)
    docs1 = [f"{r.title}\n{r.text[:HANJA_MAX]}" for r in arts.itertuples()]                       # ① 한문 그대로
    docs3 = [f"{r.title}\n{cache['llm'][r.article_id]['summary']}" for r in arts.itertuples()]   # ③ 한국어 요약
    for key, docs in (("vec1", docs1), ("vec3", docs3)):
        cache.setdefault(key, {})
        need = [(i, d) for i, d in zip(ids, docs) if i not in cache[key]]
        if need:
            print(f"[2/3] 문서 임베딩({key}) {len(need)}건")
            for i, v in zip([n[0] for n in need], embed([n[1] for n in need], "RETRIEVAL_DOCUMENT")):
                cache[key][i] = v
            save()

    # 3) 질문 임베딩 (질문은 RETRIEVAL_QUERY로!)
    cache.setdefault("q_vec", {})
    need = [i for i in ids if i not in cache["q_vec"]]
    if need:
        print(f"[3/3] 질문 임베딩 {len(need)}건")
        for i, v in zip(need, embed([cache["llm"][i]["question"] for i in need], "RETRIEVAL_QUERY")):
            cache["q_vec"][i] = v
        save()

    # 4) 채점
    q = [cache["q_vec"][i] for i in ids]
    r1 = score(q, [cache["vec1"][i] for i in ids])
    r3 = score(q, [cache["vec3"][i] for i in ids])
    print(f"\n===== 결과 (후보 {len(ids)}개 중 정답 기사 순위) =====")
    summarize(r1, "① 한문 그대로")
    summarize(r3, "③ 한국어 요약")

    pd.DataFrame({
        "article_id": ids,
        "title": arts["title"],
        "question": [cache["llm"][i]["question"] for i in ids],
        "rank_hanja(①)": r1,
        "rank_summary(③)": r3,
        "summary_kor": [cache["llm"][i]["summary"] for i in ids],
        "text_head": [t[:80] for t in arts["text"]],
    }).to_csv(RESULT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n결과 저장: {RESULT_PATH}")
    print("→ summary_kor 열을 직접 읽어서 요약이 원문과 맞는지(특히 인명·연도) 꼭 확인하세요.")


if __name__ == "__main__":
    main()
