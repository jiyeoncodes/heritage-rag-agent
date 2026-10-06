# clean_sillok.py
# ------------------------------------------------------------
# collect_sillok.py 가 모은 실록 기사(data/raw/sillok_heritage_articles.csv)에서
# "유산 이야기가 아닌 기사"를 걸러내고, RAG/관계 추출에 바로 쓸 수 있게 다듬는 스크립트예요.
#
# 왜 필요한가?
#   수집 결과 15,500여 건 중 상당수가 잡음이었어요.
#     - 너무 짧은 기사   예) "○朝壽康宮。" 한 줄
#     - 종묘만 걸린 기사  대부분 제사 절차·거둥 기록이라 유산 이야기가 아님
#     - 산릉·능침·천릉 같은 "일반 용어"만 걸린 기사  (어느 능인지 알 수 없음)
#     - 정릉동 오탐     '정릉동'(선조 때 행궁이 있던 동네 이름)이 '정릉' 키워드로 잘못 걸림
#
# 처리 흐름 (원본 raw 파일은 절대 수정하지 않고, 결과는 data/processed/ 에 따로 저장해요)
#   1) 오탐 문구(정릉동)를 가린 뒤 키워드를 다시 찾아서 걸린 키워드를 바로잡아요.
#   2) 아래 규칙으로 기사를 걸러내요. 걸러낸 기사는 이유와 함께 별도 파일에 남겨요(나중에 확인용).
#        ① 오탐만 걸림   ② 의례서(오례) 부록   ③ 종묘만 걸림   ④ 일반 용어만 걸림   ⑤ 너무 짧음
#   3) 남은 기사에 아래 정보를 덧붙여요.
#        - date_label     "세종실록 1년 1월 6일" 같은 날짜 표시
#        - tomb_detail    같은 한글 이름이 가리키는 능을 한자로 구분 (예: 영릉 = 英陵→세종 / 寧陵→효종)
#        - possible_china_tomb  중국 황제릉(명나라 孝陵·長陵 등)일 수 있는 기사 표시
#        - needs_split    본문이 길어서 나눠서 임베딩해야 할 수 있는 기사 표시
#        - source_url     실록 사이트의 해당 기사 주소 (출처 링크용)
#        - document_text  RAG에 넣을 본문: "[세종실록 1년 1월 6일] 한글제목 - 한문 본문"
#
# 실행 방법 (backend 폴더에서):   python scripts\clean_sillok.py
#   옵션 예)  python scripts\clean_sillok.py --min-length 80
#             python scripts\clean_sillok.py --keep-shrine-only     (종묘만 걸린 기사도 남김)
#
# 결과 파일 (backend/data/processed/)
#   - sillok_heritage_articles_clean.csv   : 남긴 기사
#   - sillok_clean_dropped.csv             : 걸러낸 기사와 이유
#
# 검증 상태: 사용자가 올려 준 실제 수집 결과(15,557건)로 실행해 보았어요.
#   다만 "이 규칙이 유산 이야기를 잘 남기는지"는 사람이 샘플을 읽어 보고 판단해야 해요(맨 아래 안내 참고).
# ------------------------------------------------------------

import argparse                      # 명령줄 옵션(--min-length 등)을 받는 라이브러리
import re                            # 글자 패턴(정규식) 라이브러리
from pathlib import Path             # 운영체제에 상관없이 경로를 다루는 라이브러리

import pandas as pd                  # 표 데이터를 다루고 CSV로 저장하는 라이브러리

# collect_sillok.py 에 이미 만들어 둔 "키워드 찾기" 기능을 그대로 가져와 써요. (같은 scripts 폴더에 있어야 해요)
from collect_sillok import match_keywords, ALL_GROUPS


# ------------------------------------------------------------
# 0. 경로 설정 (다른 스크립트와 같은 방식: 이 파일 위치를 기준으로 계산)
# ------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent         # backend/scripts/
PROJECT_ROOT = SCRIPT_DIR.parent                      # backend/
RAW_CSV = PROJECT_ROOT / "data" / "raw" / "sillok_heritage_articles.csv"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_CSV = PROCESSED_DIR / "sillok_heritage_articles_clean.csv"
DROPPED_CSV = PROCESSED_DIR / "sillok_clean_dropped.csv"


# ------------------------------------------------------------
# 1. 설정값
# ------------------------------------------------------------
DEFAULT_MIN_LENGTH = 50           # 이보다 짧은 기사는 걸러요 (글자 수)
SPLIT_THRESHOLD = 2000            # 이보다 긴 기사는 needs_split 표시 (나눠서 임베딩할지 나중에 결정)

# 오탐 문구: "이 글자가 들어 있으면 그 부분은 키워드로 치지 말자"
#   {키워드 이름: [가릴 문구들]}   예) '정릉동'은 동네 이름이라 정릉(능)이 아니에요.
FALSE_POSITIVE_TERMS = {
    "정릉": ["貞陵洞", "정릉동"],
}

# 같은 한글 이름이 여러 능을 가리켜서, 한자로 구분하는 표예요.   한자 → (한글 능호, 누구의 능인지)
HANJA_TOMBS = {
    "健元陵": ("건원릉", "태조"), "齊陵": ("제릉", "신의왕후"), "厚陵": ("후릉", "정종"), "獻陵": ("헌릉", "태종"),
    "英陵": ("영릉", "세종"), "寧陵": ("영릉", "효종"), "永陵": ("영릉", "진종"), "顯陵": ("현릉", "문종"),
    "莊陵": ("장릉", "단종"), "長陵": ("장릉", "인조"), "章陵": ("장릉", "원종"), "光陵": ("광릉", "세조"),
    "昌陵": ("창릉", "예종"), "敬陵": ("경릉", "덕종"), "景陵": ("경릉", "헌종"), "恭陵": ("공릉", "장순왕후"),
    "順陵": ("순릉", "공혜왕후"), "宣陵": ("선릉", "성종"), "靖陵": ("정릉", "중종"), "貞陵": ("정릉", "신덕왕후"),
    "孝陵": ("효릉", "인종"), "康陵": ("강릉", "명종"), "穆陵": ("목릉", "선조"), "崇陵": ("숭릉", "현종"),
    "明陵": ("명릉", "숙종"), "翼陵": ("익릉", "인경왕후"), "懿陵": ("의릉", "경종"), "弘陵": ("홍릉", "정성왕후"),
    "洪陵": ("홍릉", "고종"), "元陵": ("원릉", "영조"), "隆陵": ("융릉", "장조"), "健陵": ("건릉", "정조"),
    "仁陵": ("인릉", "순조"), "綏陵": ("수릉", "문조"), "睿陵": ("예릉", "철종"), "裕陵": ("유릉", "순종"),
    "思陵": ("사릉", "정순왕후"), "溫陵": ("온릉", "단경왕후"), "昭陵": ("소릉", "현덕왕후"), "徽陵": ("휘릉", "장렬왕후"),
    "惠陵": ("혜릉", "단의왕후"),
}
# 긴 이름부터 찾기 위해 미리 길이 순으로 정렬 (健元陵 안의 元陵을 따로 세지 않으려고)
HANJA_TOMBS_SORTED = sorted(HANJA_TOMBS, key=lambda k: -len(k))

# 중국 황제릉과 이름이 겹치는 한자 (예: 孝陵 = 명 태조의 능, 長陵 = 명 영락제의 능)
CHINA_COLLISION = {"孝陵", "獻陵", "長陵", "景陵", "裕陵", "康陵", "永陵", "昭陵", "思陵"}
# 중국 황제 시대(명나라 연호)가 글에 나오면 "중국 능 이야기일 수 있음" 표시를 해요.
CHINA_MARKERS = re.compile("洪武|永樂|宣德|正統|景泰|天順|成化|弘治|正德|嘉靖|隆慶|萬曆|天啓|崇禎")


# ------------------------------------------------------------
# 2. 도우미 함수들
# ------------------------------------------------------------
def rematch_without_false_positives(text):
    """
    오탐 문구를 가린 글에서 키워드를 다시 찾아요.
    (예: '貞陵洞行宮' 을 가리면 '貞陵'이 남지 않아서 정릉 키워드가 빠져요.)
    돌려주는 값: {대표이름: 묶음}
    """
    masked = text
    for phrases in FALSE_POSITIVE_TERMS.values():
        for p in phrases:
            masked = masked.replace(p, "\0" * len(p))
    return match_keywords(masked, set(ALL_GROUPS))


def resolve_tombs(text):
    """
    본문에서 한자 능호를 찾아 "영릉(세종);장릉(인조)" 처럼 풀어 써요.
    돌려주는 값: (설명 문자열, 찾은 한자 집합)
    """
    work = text
    for phrases in FALSE_POSITIVE_TERMS.values():
        for p in phrases:
            work = work.replace(p, "\0" * len(p))
    found, labels = set(), []
    for hanja in HANJA_TOMBS_SORTED:
        if hanja in work:
            found.add(hanja)
            work = work.replace(hanja, "\0" * len(hanja))      # 긴 이름을 찾았으면 지워서 짧은 이름이 또 걸리지 않게
            hangul, who = HANJA_TOMBS[hanja]
            labels.append(f"{hangul}({who})")
    return ";".join(sorted(set(labels))), found


def make_date_label(row):
    """'세종실록 1년 1월 6일' 같은 날짜 표시를 만들어요. 재위년이 없으면(총서 등) '총서'로 둬요."""
    reign = row["reign_title"]
    if not row["regnal_year"]:
        return f"{reign} 총서"
    leap = "윤" if row["leap_month"] else ""
    return f"{reign} {row['regnal_year']}년 {leap}{row['month']}월 {row['day']}일"


def drop_reason(row, args):
    """걸러야 하는 기사면 이유를, 남겨도 되면 빈 문자열을 돌려줘요. (먼저 맞는 규칙의 이유를 써요)"""
    if not row["matched_keywords"]:
        return "① 오탐만 걸림 (정릉동 등)"
    if row["title"].startswith("五禮"):
        return "② 의례서(오례) 부록"
    if row["matched_keywords"] == "종묘" and not args.keep_shrine_only:
        return "③ 종묘만 걸림 (제례·거둥)"
    if row["match_groups"] == "tomb_general" and not args.keep_general_only:
        return "④ 일반 용어만 걸림 (산릉·능침·천릉)"
    if int(row["text_length"]) < args.min_length:
        return f"⑤ 너무 짧음 (<{args.min_length}자)"
    return ""


# ------------------------------------------------------------
# 3. 전체 실행 흐름
# ------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="실록 수집 결과에서 잡음 기사를 걸러내고 다듬기")
    parser.add_argument("--min-length", type=int, default=DEFAULT_MIN_LENGTH, help=f"최소 글자 수 (기본 {DEFAULT_MIN_LENGTH})")
    parser.add_argument("--keep-shrine-only", action="store_true", help="종묘만 걸린 기사도 남기기")
    parser.add_argument("--keep-general-only", action="store_true", help="일반 용어(산릉 등)만 걸린 기사도 남기기")
    args = parser.parse_args()

    if not RAW_CSV.exists():
        raise SystemExit(f"수집 결과가 없어요: {RAW_CSV}\n먼저 python scripts\\collect_sillok.py 를 실행해 주세요.")

    # 모든 칸을 글자(str)로 읽어요. (숫자로 읽으면 빈 칸이 NaN/소수로 바뀌어 헷갈려요.)
    df = pd.read_csv(RAW_CSV, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    total = len(df)
    print(f"원본 {total:,}건을 읽었어요: {RAW_CSV.name}\n")

    # --- 1) 오탐 바로잡기 ---
    old_keywords = df["matched_keywords"].copy()
    new_matches = df["text"].map(rematch_without_false_positives)
    df["matched_keywords"] = new_matches.map(lambda m: ";".join(sorted(m)))
    df["match_groups"] = new_matches.map(lambda m: ";".join(sorted(set(m.values()))))
    changed = (old_keywords != df["matched_keywords"]).sum()
    print(f"오탐을 바로잡아 걸린 키워드가 바뀐 기사: {changed:,}건")

    # --- 2) 걸러내기 ---
    df["_reason"] = df.apply(lambda r: drop_reason(r, args), axis=1)
    dropped = df[df["_reason"] != ""].copy()
    kept = df[df["_reason"] == ""].copy()

    # --- 3) 남은 기사 다듬기 ---
    kept["date_label"] = kept.apply(make_date_label, axis=1)
    resolved = kept["text"].map(resolve_tombs)
    kept["tomb_detail"] = resolved.map(lambda t: t[0])
    kept["possible_china_tomb"] = [
        "Y" if (found & CHINA_COLLISION) and CHINA_MARKERS.search(text) else ""
        for (_, found), text in zip(resolved, kept["text"])
    ]
    kept["needs_split"] = kept["text_length"].map(lambda n: "Y" if int(n) > SPLIT_THRESHOLD else "")
    # 실록 사이트 주소: 맨 앞 글자를 w(원문) → k(국역 화면)로 바꾸면 한 화면에서 원문과 국역을 같이 볼 수 있어요.
    kept["source_url"] = kept["article_id"].map(lambda i: f"https://sillok.history.go.kr/id/k{i[1:]}")
    kept["document_text"] = kept.apply(lambda r: f"[{r['date_label']}] {r['title']} - {r['text']}", axis=1)

    columns = ["article_id", "reign_title", "regnal_year", "month", "leap_month", "day", "date_label", "title", "text",
               "text_length", "language", "match_groups", "matched_keywords", "tomb_detail", "possible_china_tomb",
               "needs_split", "source_url", "document_text", "source_file", "content_hash"]
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    kept[columns].to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    dropped[["article_id", "_reason", "title", "text_length", "matched_keywords", "match_groups"]] \
        .rename(columns={"_reason": "drop_reason"}).to_csv(DROPPED_CSV, index=False, encoding="utf-8-sig")

    # --- 4) 결과 보고 ---
    print(f"\n===== 결과 =====")
    print(f"남긴 기사 {len(kept):,}건 / 걸러낸 기사 {len(dropped):,}건 (전체 {total:,}건)")
    print("\n걸러낸 이유별 건수:")
    print(dropped["_reason"].value_counts().sort_index().to_string())
    print("\n남긴 기사의 묶음별 건수:")
    print(kept["match_groups"].value_counts().head(8).to_string())
    print(f"\n길어서 나눠야 할 수 있는 기사(>{SPLIT_THRESHOLD}자): {(kept['needs_split'] == 'Y').sum():,}건")
    print(f"중국 능일 수 있는 기사 표시: {(kept['possible_china_tomb'] == 'Y').sum():,}건")
    print(f"능을 한자로 구분한 기사: {(kept['tomb_detail'] != '').sum():,}건")
    print("\n남긴 기사 중 왕대별 상위 5:")
    print(kept["reign_title"].value_counts().head(5).to_string())
    print(f"\n저장: {OUTPUT_CSV}\n      {DROPPED_CSV}")
    print("\n[확인 방법] 걸러낸 파일(sillok_clean_dropped.csv)을 엑셀로 열어 '남겼어야 할 기사'가 섞여 있는지 몇 줄만 훑어봐 주세요.")


if __name__ == "__main__":
    main()
