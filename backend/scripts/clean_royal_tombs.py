# clean_royal_tombs.py
# ------------------------------------------------------------
# collect_royal_tombs.py가 만든 heritage_royal_tombs_detail.csv(조선왕릉 18 + 경희궁지 1 + 5대 궁궐 개요 5 = 24건)를 읽어서
#   ① 설명글의 HTML 태그(<br/>, <b> 등)를 지우고
#   ② "명칭변경 되었습니다" 같은 안내 문장을 빼고
#   ③ 공백·줄바꿈을 정리한 뒤
#   ④ RAG에 쓸 본문 "document_text"를 만들어 새 CSV로 저장하는 스크립트예요.
#
# 실행 방법 (backend/scripts 폴더에서):  python clean_royal_tombs.py
# 입력: data/raw/heritage_royal_tombs_detail.csv  (원본은 건드리지 않아요)
# 출력: data/processed/heritage_royal_tombs_clean.csv
#
# 본문 형식은 기존 궁궐 데이터와 똑같이 "[분류명] 유산명 - 설명글" 로 만들어요.
#   예) [조선왕릉] 영월 장릉 - 조선 6대 단종(재위 1452∼1455)의 무덤이다. ...
#       [경희궁] 경희궁지 - 원종의 집터에 세워진 조선후기의 대표적인 이궁이다. ...
#       [창덕궁] 개요 - 창덕궁은 1405년(태종 5)에 창건한 조선왕조의 궁궐이다. ...
# ------------------------------------------------------------

import re                    # 정규식: 글자 패턴을 찾고 바꾸는 라이브러리
from pathlib import Path     # 운영체제에 상관없이 경로를 다루는 라이브러리

import pandas as pd          # 표 데이터를 다루는 라이브러리


# ------------------------------------------------------------
# 0. 경로 설정
# ------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent              # backend/scripts/
PROJECT_ROOT = SCRIPT_DIR.parent                           # backend/
INPUT_CSV = PROJECT_ROOT / "data" / "raw" / "heritage_royal_tombs_detail.csv"
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_CSV = OUTPUT_DIR / "heritage_royal_tombs_clean.csv"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# DB의 source(출처) 컬럼에 넣을 값. 공공데이터를 쓸 때는 어디서 가져왔는지 출처를 밝히는 게 이용 조건이에요.
SOURCE_NAME = "국가유산청 국가유산 종합 Open API"

# 종목 이름 -> 종목 코드. 지정번호(ccba_asno)는 종목이 다르면 겹치므로 (종목 코드, 지정번호)를 DB의 키로 써요.
# 모르는 종목이 나오면 조용히 넘어가지 않고 오류를 내요. (엉뚱한 코드로 저장되는 걸 막으려고요)
KIND_CODE_BY_NAME = {"국보": "11", "보물": "12", "사적": "13", "천연기념물": "16",
                     "국가무형유산": "17", "국가등록유산": "79"}

# collect_royal_tombs.py가 만들어 줘야 하는 컬럼들 (없으면 예전 버전으로 수집한 파일이라는 뜻)
REQUIRED_COLUMNS = ["ccba_asno", "group", "gung_name", "heritage_type", "display_name",
                    "kind_name", "content", "img_url"]


# ------------------------------------------------------------
# 1. 정리 규칙 (정규식 패턴)
# ------------------------------------------------------------
BR_TAG = re.compile(r"<br\s*/?>", flags=re.IGNORECASE)   # <br/>, <br>, <br /> → 줄바꿈으로 바꿀 태그
ANY_TAG = re.compile(r"<[^>]+>")                           # 그 밖의 모든 <...> 태그 (<b>, </b> 등) → 삭제

# "※(동구릉 → 구리 동구릉)으로 명칭변경 되었습니다. (2011.07.28 고시)" 같은 안내 줄 전체.
# 설명(내용)이 아니라 행정 안내라서, 검색에 방해가 되므로 줄 단위로 통째로 뺍니다.
RENAME_NOTICE_LINE = re.compile(r"^\s*※.*명칭\s*변경.*$", flags=re.MULTILINE)

# 지금은 빼지 않지만 "※"로 시작하는 다른 안내 줄(예: 서삼릉 비공개 안내, 온릉 시범 개방 안내)
# 은 따로 세어서 보고해요. 오래되면 틀려질 수 있는 정보라, 남길지 말지는 사람이 판단하게 하려는 거예요.
OTHER_NOTICE_LINE = re.compile(r"^\s*※.*$", flags=re.MULTILINE)


def clean_content(text):
    """설명글 하나를 정리해서 돌려줘요. 비어 있으면 빈 문자열."""
    if not isinstance(text, str):
        return ""

    text = BR_TAG.sub("\n", text)          # ① <br/> → 줄바꿈 (문단이 나뉘던 자리를 살려요)
    text = ANY_TAG.sub("", text)           # ② 남은 태그(<b> 등) 삭제 — 안의 글자는 그대로 남아요
    text = RENAME_NOTICE_LINE.sub("", text)  # ③ 명칭변경 안내 줄 삭제

    # ④ 줄마다 앞뒤 공백을 지우고, 빈 줄은 버린 뒤 다시 합쳐요.
    #    (원본은 줄 앞에 공백 한두 칸이 붙어 있고 빈 줄이 여러 개 있어요.)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


# ------------------------------------------------------------
# 2. 실행 흐름
# ------------------------------------------------------------
def main():
    # dtype=str : 모든 컬럼을 문자열로 읽어요. 지정번호(0002710000000)의 앞자리 0이 사라지지 않게 하려는 거예요.
    # keep_default_na=False : 빈 칸을 NaN(없음)이 아니라 빈 문자열로 읽어요.
    raw = pd.read_csv(INPUT_CSV, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    print(f"원본 데이터: {len(raw)}건\n")

    missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    if missing:
        raise SystemExit(f"원본 CSV에 필요한 컬럼이 없어요: {missing}\n"
                         f"→ collect_royal_tombs.py를 최신 버전으로 다시 실행한 뒤 이 스크립트를 실행하세요.")

    before_tags = raw["content"].str.contains("<", regex=False).sum()
    before_notice = raw["content"].str.contains("명칭변경", regex=False).sum()
    print(f"정리 전: HTML 태그가 섞인 행 {before_tags}건, '명칭변경' 안내가 있는 행 {before_notice}건")

    df = pd.DataFrame()
    df["ccba_asno"] = raw["ccba_asno"]                       # 지정번호 (DB의 고유 키)
    df["group"] = raw["group"]                                # 수집 묶음: 조선왕릉 / 경희궁 / 궁궐 개요
    df["gung_name"] = raw["gung_name"]                        # DB 분류명 — 화면과 출처에 표시돼요 (조선왕릉, 경희궁, 경복궁 …)
    df["heritage_type"] = raw["heritage_type"]                # DB 유산 유형 (능역 / 개요)
    df["designation"] = raw["kind_name"]                      # DB 지정 종목 (사적)
    unknown_kinds = sorted(set(df["designation"]) - set(KIND_CODE_BY_NAME))
    if unknown_kinds:
        raise SystemExit(f"종목 코드를 모르는 종목이 있어요: {unknown_kinds} → KIND_CODE_BY_NAME에 추가하세요.")
    df["ccba_kdcd"] = df["designation"].map(KIND_CODE_BY_NAME)   # DB 종목 코드 (사적=13)
    # 시도 코드는 상세 조회에 필요한 값이라 같이 보관해요. (옛 수집 파일에 없으면 빈 값)
    df["ccba_ctcd"] = raw["ccba_ctcd"] if "ccba_ctcd" in raw.columns else ""
    df["source"] = SOURCE_NAME                                # DB 출처
    df["contents_kor"] = raw["display_name"]                  # 유산명 (영월 장릉, 경희궁지, 개요 …)
    df["content_clean"] = raw["content"].apply(clean_content)  # 정리된 설명글
    df["img_url"] = raw["img_url"]
    df["moving_urls"] = ""                                    # 이 API에는 동영상이 없어요 (DB 컬럼을 맞추려고 빈 값)

    # RAG 본문: 기존 궁궐 데이터와 같은 "[분류명] 유산명 - 설명글" 형식
    df["document_text"] = "[" + df["gung_name"] + "] " + df["contents_kor"] + " - " + df["content_clean"]
    df["document_length"] = df["document_text"].str.len()

    # ---- 검증 ----
    problems = []
    if df["content_clean"].str.contains("<", regex=False).any():
        problems.append("정리 후에도 '<' 가 남은 행이 있어요")
    if (df["content_clean"] == "").any():
        problems.append("정리 후 설명글이 빈 행이 있어요")
    if df["ccba_asno"].duplicated().any():
        problems.append("지정번호가 중복된 행이 있어요")
    if (df["ccba_asno"].str.len() != 13).any():
        problems.append("지정번호가 13자리가 아닌 행이 있어요")
    if df.duplicated(["gung_name", "contents_kor"]).any():
        problems.append("(분류명, 유산명)이 같은 행이 있어요 → 출처 표시([분류명 유산명])가 헷갈려요")
    if (df[["gung_name", "contents_kor", "heritage_type", "designation"]] == "").any().any():
        problems.append("분류명/유산명/유산 유형/지정 종목이 빈 행이 있어요")

    after_tags = df["content_clean"].str.contains("<", regex=False).sum()
    after_notice = df["content_clean"].str.contains("명칭변경", regex=False).sum()
    print(f"정리 후: HTML 태그 {after_tags}건, '명칭변경' 안내 {after_notice}건 (둘 다 0이어야 정상)\n")

    print("본문(document_text) 길이 통계:")
    print(df.groupby(["group", "heritage_type"])["document_length"].agg(["count", "min", "mean", "max"]).round(0), "\n")

    # 남겨 둔 다른 ※ 안내 줄 목록 — 운영 정보라 시간이 지나면 틀릴 수 있어서 눈으로 확인하라고 보여줘요.
    print("남겨 둔 '※' 안내 줄 (필요 없으면 알려 주세요):")
    shown = False
    for name, text in zip(df["contents_kor"], df["content_clean"]):
        for notice in OTHER_NOTICE_LINE.findall(text):
            print(f"   - {name}: {notice[:70]}")
            shown = True
    if not shown:
        print("   (없음)")

    if problems:
        print("\n⚠ 문제 발견:")
        for p in problems:
            print("   -", p)

    # 저장할 컬럼만 골라요 (content_clean은 document_text에 이미 들어 있어서 뺍니다).
    out = df[["ccba_kdcd", "ccba_asno", "ccba_ctcd", "group", "gung_name", "heritage_type", "designation", "source",
              "contents_kor", "document_text", "img_url", "moving_urls", "document_length"]]
    out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n정리된 데이터를 {OUTPUT_CSV} 에 저장했어요. (총 {len(out)}건)")


if __name__ == "__main__":
    main()
