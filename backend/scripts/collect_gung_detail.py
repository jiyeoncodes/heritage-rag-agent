# collect_gung_detail.py
# ------------------------------------------------------------
# 이전 단계(collect_gung_list.py)에서 만든 heritage_gung_list.csv 를 읽어서,
# 각 유산의 "상세조회" API(detail_link)를 하나씩 호출하고,
# 4개 언어 설명 + 상세 이미지 + 동영상 경로까지 받아 CSV로 저장하는 스크립트입니다.
#
# 실행 순서:
#   1) collect_gung_list.py를 먼저 실행해서 heritage_gung_list.csv를 만들어 둡니다.
#   2) 이 파일을 같은 폴더에 두고 실행합니다: python collect_gung_detail.py
#
# 결과물: heritage_gung_detail.csv (같은 폴더에 생성됩니다)
# ------------------------------------------------------------

import requests                      # 웹 API에 요청을 보내는 라이브러리
import xml.etree.ElementTree as ET   # XML 문자열을 분석(파싱)하는 라이브러리
import pandas as pd                  # 표 형태 데이터를 다루고 CSV로 저장하는 라이브러리
import time                          # 요청 사이에 잠깐 쉬기 위한 라이브러리
from pathlib import Path             # 운영체제에 상관없이 폴더 경로를 안전하게 다루는 라이브러리


# ------------------------------------------------------------
# 0. 폴더 구조에 맞는 경로 설정
# ------------------------------------------------------------

# 이 파일(collect_gung_detail.py)은 scripts/ 폴더 안에 있다고 가정해요.
SCRIPT_DIR = Path(__file__).resolve().parent       # scripts/
PROJECT_ROOT = SCRIPT_DIR.parent                    # heritage-rag-agent/
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"        # data/raw/
DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)     # 폴더가 없으면 자동으로 만들어줘요.


# ------------------------------------------------------------
# 1. 기본 설정값
# ------------------------------------------------------------

INPUT_CSV = DATA_RAW_DIR / "heritage_gung_list.csv"     # 이전 단계에서 만든 목록 파일 (읽어올 파일)
OUTPUT_CSV = DATA_RAW_DIR / "heritage_gung_detail.csv"  # 이번에 새로 만들 상세 파일 (저장할 파일)

# 상세조회 응답에서 뽑아올 필드 이름들을 미리 목록으로 정리해 둡니다.
# (뒤에서 이 목록을 반복문으로 돌면서 하나씩 꺼내 쓸 거예요.)
# ※ 실제 응답을 확인해 보니, 태그 하나에 값 하나가 깔끔하게 들어 있는 필드는 이 8개뿐이었어요.
#    imgUrl(대표 이미지)과 moving(동영상)은 구조가 조금 달라서 아래에서 따로 처리해요.
DETAIL_FIELDS = [
    "contents_kor", "contents_eng", "contents_jpa", "contents_chi",       # 국가유산명 (4개 언어)
    "explanation_kor", "explanation_eng", "explanation_jpa", "explanation_chi",  # 국가유산 설명 (4개 언어)
]


# ------------------------------------------------------------
# 2. 상세조회 API를 호출해서 XML 원문을 받아오는 함수
# ------------------------------------------------------------
def fetch_detail_xml(detail_url):
    """
    목록조회 응답에 이미 완성되어 들어 있던 detail_link 주소로 요청을 보내고,
    응답 XML을 문자열 그대로 반환하는 함수예요.
    (목록조회 때와 다르게, 주소가 이미 완성되어 있어서 params 없이 바로 호출해요.)
    """
    response = requests.get(
        detail_url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    response.raise_for_status()  # 200(정상)이 아니면 예외를 발생시켜요.
    response.encoding = "utf-8"
    return response.text


# ------------------------------------------------------------
# 3. 상세조회 XML을 분석해서 딕셔너리로 바꾸는 함수
# ------------------------------------------------------------
def parse_gung_detail_xml(xml_text):
    """
    상세조회 XML 문자열을 받아서, 우리가 원하는 필드들만 뽑아
    딕셔너리 하나로 반환하는 함수예요.
    (상세조회는 유산 1개짜리 정보만 오기 때문에, 목록조회 때처럼
     여러 개를 반복(for)할 필요 없이 값 하나씩만 꺼내면 돼요.)
    """
    root = ET.fromstring(xml_text)

    # find(".//태그이름")의 ".//"는 "이 태그 밑의 모든 깊이에서 찾아라"라는 뜻이에요.
    # 예를 들어 imgUrl은 실제로는 <mainImage><imgUrl>...</imgUrl></mainImage>처럼
    # 한 단계 안쪽에 있는데, ".//"를 쓰면 깊이에 상관없이 찾아낼 수 있어요.
    def get_text(tag_name):
        tag = root.find(f".//{tag_name}")
        if tag is None or tag.text is None:
            return ""
        return tag.text.strip()

    # 같은 이름의 태그가 "여러 개" 있을 수 있는 경우에 쓰는 함수예요.
    # 예: <listMoving> 안에 <moving> 태그가 3개 들어 있는 경우
    # findall()로 전부 찾은 뒤, 리스트로 모아서 반환해요.
    def get_all_texts(tag_name):
        tags = root.findall(f".//{tag_name}")
        # 태그는 있지만 내용이 비어 있는 경우(예: 빈 listImg)는 제외해요.
        return [t.text.strip() for t in tags if t.text and t.text.strip()]

    # DETAIL_FIELDS 목록에 있는 이름들을 하나씩 꺼내서 딕셔너리를 만들어요.
    detail = {field: get_text(field) for field in DETAIL_FIELDS}

    # 대표 이미지: <mainImage> 안의 <imgUrl> 하나만 있어서 get_text로 충분해요.
    detail["img_url"] = get_text("imgUrl")

    # 동영상: <listMoving> 안에 <moving>이 여러 개 있을 수 있어서 get_all_texts로 모두 모아요.
    # CSV 한 칸에는 값을 하나만 넣을 수 있어서, 세미콜론( ; )으로 이어 붙여 하나의 문자열로 저장해요.
    # (나중에 필요할 때 moving_urls.split(" ; ")로 다시 리스트로 나눌 수 있어요.)
    detail["moving_urls"] = " ; ".join(get_all_texts("moving"))

    return detail


# ------------------------------------------------------------
# 4. 전체 실행 흐름 (메인 함수)
# ------------------------------------------------------------
def main():
    # ① 이전 단계에서 만든 목록 CSV를 읽어와요.
    #    이 표에는 gung_number, gung_name, serial_number, detail_code, detail_link 등이 들어 있어요.
    list_df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig")

    print(f"총 {len(list_df)}건의 유산에 대해 상세조회를 시작합니다...\n")

    all_details = []   # 성공적으로 받아온 상세 정보를 모을 리스트
    failed_items = []  # 실패한 항목을 기록해 둘 리스트 (나중에 다시 시도하거나 확인하기 위해)

    # ② 목록 표를 한 줄(행)씩 반복해요. iterrows()는 (인덱스번호, 그 줄의 데이터) 쌍을 줘요.
    for idx, row in list_df.iterrows():
        gung_name = row["gung_name"]
        contents_kor = row["contents_kor"]
        detail_url = row["detail_link"]

        # 진행 상황을 눈으로 확인할 수 있도록 출력해요.
        print(f"[{idx + 1}/{len(list_df)}] {gung_name} - {contents_kor} 상세조회 중...")

        try:
            # ③ 상세조회 API 호출해서 XML 받기
            xml_text = fetch_detail_xml(detail_url)

            # ④ XML을 파싱해서 딕셔너리로 바꾸기
            detail = parse_gung_detail_xml(xml_text)

            # ⑤ 목록 정보(궁 번호, 이름, 순번 등)와 상세 정보를 하나로 합쳐요.
            #    나중에 어떤 유산의 상세 정보인지 알아볼 수 있게 하기 위해서예요.
            merged = {
                "gung_number": row["gung_number"],
                "gung_name": gung_name,
                "serial_number": row["serial_number"],
                "detail_code": row["detail_code"],
                **detail,  # 위에서 만든 상세 정보 딕셔너리를 그대로 펼쳐서 합쳐요.
            }
            all_details.append(merged)

        except requests.exceptions.RequestException as e:
            print(f"    ! 요청 오류: {e}")
            failed_items.append((gung_name, contents_kor, str(e)))

        except ET.ParseError as e:
            print(f"    ! XML 파싱 오류: {e}")
            failed_items.append((gung_name, contents_kor, str(e)))

        # 서버에 너무 빠르게 연속으로 요청하지 않도록 짧게 쉬어요.
        # 상세조회는 목록조회보다 호출 횟수가 훨씬 많아서 (유산 개수만큼) 조금 더 신경 써요.
        time.sleep(0.3)

    # ------------------------------------------------------------
    # 5. 결과 저장
    # ------------------------------------------------------------
    detail_df = pd.DataFrame(all_details)
    detail_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    print(f"\n총 {len(detail_df)}건을 {OUTPUT_CSV} 파일로 저장했습니다.")

    # 실패한 항목이 있으면 알려줘요. (개수가 적으면 나중에 수동으로 다시 시도해볼 수 있어요.)
    if failed_items:
        print(f"\n※ 실패한 항목이 {len(failed_items)}건 있습니다:")
        for gung_name, contents_kor, error_msg in failed_items:
            print(f"   - {gung_name} / {contents_kor} : {error_msg}")


if __name__ == "__main__":
    main()
