# clean_gung_detail.py
# ------------------------------------------------------------
# collect_gung_detail.py로 만든 heritage_gung_detail.csv를 읽어서,
# 설명 글에 섞여 있는 HTML 태그 잔재(<br/> 등)를 정리하고,
# RAG(검색 기반 답변)에 바로 쓸 수 있는 "document_text" 컬럼을 추가한 뒤
# 새 CSV로 저장하는 스크립트입니다.
#
# 실행 순서:
#   1) collect_gung_detail.py를 먼저 실행해서 heritage_gung_detail.csv를 만들어 둡니다.
#   2) 이 파일을 같은 폴더에 두고 실행합니다: python clean_gung_detail.py
#
# 결과물: heritage_gung_detail_clean.csv (같은 폴더에 생성됩니다)
# ------------------------------------------------------------

import re             # 정규식(regular expression)으로 글자 패턴을 찾고 바꾸는 라이브러리
import pandas as pd   # 표 형태 데이터를 다루는 라이브러리
from pathlib import Path  # 운영체제에 상관없이 폴더 경로를 안전하게 다루는 라이브러리


# ------------------------------------------------------------
# 0. 폴더 구조에 맞는 경로 설정
# ------------------------------------------------------------

# 이 파일(clean_gung_detail.py)은 scripts/ 폴더 안에 있다고 가정해요.
SCRIPT_DIR = Path(__file__).resolve().parent           # scripts/
PROJECT_ROOT = SCRIPT_DIR.parent                        # heritage-rag-agent/
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"            # 원본이 있는 곳 (읽기)
DATA_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"  # 정리 결과를 저장할 곳 (쓰기)
DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)   # 폴더가 없으면 자동으로 만들어줘요.


# ------------------------------------------------------------
# 1. 기본 설정값
# ------------------------------------------------------------

INPUT_CSV = DATA_RAW_DIR / "heritage_gung_detail.csv"                  # 정리할 원본 파일 (data/raw)
OUTPUT_CSV = DATA_PROCESSED_DIR / "heritage_gung_detail_clean.csv"     # 정리 후 저장할 파일 (data/processed)

# 정리(클린업)가 필요한 텍스트 컬럼들을 미리 목록으로 정리해 둡니다.
# 국가유산명(contents_*)과 설명(explanation_*) 컬럼이 대상이에요.
TEXT_COLUMNS = [
    "contents_kor", "contents_eng", "contents_jpa", "contents_chi",
    "explanation_kor", "explanation_eng", "explanation_jpa", "explanation_chi",
]

# 정규식에서 사용할 패턴을 미리 컴파일해 둡니다. (반복 사용할 때 속도가 더 빨라요.)
# <br/>, <br>, <br /> 처럼 줄바꿈을 나타내는 태그를 찾는 패턴이에요.
BR_TAG_PATTERN = re.compile(r"<br\s*/?>", flags=re.IGNORECASE)

# <br/> 말고 혹시 남아 있을 수 있는 다른 HTML 태그(<...> 형태)를 찾는 패턴이에요.
# 예: <b>, </span> 같은 것들을 잡아내기 위한 안전장치예요.
ANY_TAG_PATTERN = re.compile(r"<[^>]+>")

# 여러 개의 공백이나 줄바꿈이 겹쳐 있는 경우를 하나로 줄이기 위한 패턴이에요.
MULTI_SPACE_PATTERN = re.compile(r"[ \t]+")
MULTI_NEWLINE_PATTERN = re.compile(r"\n{2,}")


# ------------------------------------------------------------
# 2. 글자 하나를 정리하는 함수
# ------------------------------------------------------------
def clean_text(text):
    """
    문자열 하나를 받아서 HTML 태그 잔재를 없애고 공백을 정리한 뒤 반환해요.
    빈 값(NaN)이 들어오면 빈 문자열로 바꿔서 오류 없이 처리되게 해요.
    """
    # pandas가 빈 칸을 float형 NaN으로 읽는 경우가 있어서, 문자열이 아니면 빈 문자열 처리해요.
    if not isinstance(text, str):
        return ""

    # ① <br/> 계열 태그를 줄바꿈 문자(\n)로 바꿔요.
    #    (완전히 지우지 않고 줄바꿈으로 바꾸는 이유: 원래 문단이 나뉘던 지점을 살리기 위해서예요.)
    text = BR_TAG_PATTERN.sub("\n", text)

    # ② 혹시 남아 있는 다른 HTML 태그가 있다면 전부 제거해요.
    text = ANY_TAG_PATTERN.sub("", text)

    # ③ 연속된 공백/탭을 하나의 공백으로 줄여요.
    text = MULTI_SPACE_PATTERN.sub(" ", text)

    # ④ 연속된 줄바꿈(\n\n\n 등)을 하나의 줄바꿈으로 줄여요.
    text = MULTI_NEWLINE_PATTERN.sub("\n", text)

    # ⑤ 문장 앞뒤에 남은 공백이나 줄바꿈을 제거해요.
    return text.strip()


# ------------------------------------------------------------
# 3. 전체 실행 흐름 (메인 함수)
# ------------------------------------------------------------
def main():
    # ① 원본 CSV를 읽어와요.
    df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig")
    print(f"원본 데이터: 총 {len(df)}건\n")

    # ② 정리 전 상태를 먼저 확인해요. (나중에 몇 건이 바뀌었는지 비교하기 위해서예요.)
    before_br_count = df["explanation_kor"].fillna("").str.contains("<br", case=False).sum()
    print(f"정리 전, explanation_kor에 <br 태그가 섞인 행: {before_br_count}건")

    # ③ TEXT_COLUMNS에 있는 컬럼들을 하나씩 정리해요.
    #    .apply(clean_text)는 그 컬럼의 모든 값에 clean_text 함수를 하나씩 적용해줘요.
    for column in TEXT_COLUMNS:
        df[column] = df[column].apply(clean_text)

    # ④ 정리 후 상태를 다시 확인해요. 0건이 나와야 정상이에요.
    after_br_count = df["explanation_kor"].str.contains("<br", case=False).sum()
    print(f"정리 후, explanation_kor에 <br 태그가 섞인 행: {after_br_count}건\n")

    # ⑤ 정리 과정에서 내용이 통째로 사라진 행이 있는지 확인해요. (혹시 모를 실수 방지)
    empty_after_clean = (df["explanation_kor"].str.strip() == "").sum()
    if empty_after_clean > 0:
        print(f"⚠ 주의: 정리 후 explanation_kor이 빈 값이 된 행이 {empty_after_clean}건 있어요. 확인이 필요해요.")

    # ⑥ 설명 글의 길이(글자 수)를 계산해서 컬럼으로 추가해요.
    #    나중에 너무 긴 설명을 여러 조각으로 나눌지(청킹) 판단하는 데 참고할 수 있어요.
    df["explanation_kor_length"] = df["explanation_kor"].str.len()

    print("설명 글 길이(explanation_kor_length) 통계:")
    print(f"   최소: {df['explanation_kor_length'].min()}자")
    print(f"   평균: {df['explanation_kor_length'].mean():.0f}자")
    print(f"   최대: {df['explanation_kor_length'].max()}자\n")

    # ⑦ RAG(검색 기반 답변)에서 바로 쓸 수 있도록, "이름 + 설명"을 합친 본문 컬럼을 만들어요.
    #    예: "[경복궁] 근정전 - 근정전은 ... 입니다."
    #    이렇게 이름을 본문 앞에 붙여두면, 검색할 때 이름만으로도 잘 찾아질 확률이 높아져요.
    df["document_text"] = (
        "[" + df["gung_name"] + "] " + df["contents_kor"] + " - " + df["explanation_kor"]
    )

    # ⑧ 정리된 결과를 새 CSV로 저장해요. (원본 파일은 그대로 남겨 둬서 비교할 수 있게 해요.)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"정리된 데이터를 {OUTPUT_CSV} 파일로 저장했습니다. (총 {len(df)}건)")


if __name__ == "__main__":
    main()
