# collect_gung_list.py
# ------------------------------------------------------------
# 궁궐·종묘 "목록조회" API를 5개 궁(경복궁~종묘)에 대해 모두 호출해서
# XML 응답을 받고, 필요한 값만 뽑아서 CSV 파일로 저장하는 스크립트입니다.
#
# 실행 방법: 터미널(명령 프롬프트)에서
#     python collect_gung_list.py
# 라고 입력하면 실행됩니다.
#
# 결과물: 이 파일과 같은 폴더에 heritage_gung_list.csv 가 생성됩니다.
# ------------------------------------------------------------

import requests                      # 웹 API에 "데이터 줘"라고 요청을 보내는 라이브러리
import xml.etree.ElementTree as ET   # XML 문자열을 파이썬이 다루기 쉬운 구조로 분석(파싱)하는 라이브러리
import pandas as pd                  # 표(엑셀 같은) 형태 데이터를 다루고 CSV로 저장하는 라이브러리
import time                          # 여러 번 호출할 때 서버에 부담을 덜 주려고 잠깐 쉬는 데 사용
from pathlib import Path             # 운영체제에 상관없이 폴더 경로를 안전하게 다루는 라이브러리


# ------------------------------------------------------------
# 0. 폴더 구조에 맞는 저장 경로 설정
# ------------------------------------------------------------

# 이 파일(collect_gung_list.py)은 scripts/ 폴더 안에 있다고 가정해요.
# .parent를 한 번 쓰면 scripts/ 폴더, 한 번 더 쓰면 프로젝트 루트 폴더가 돼요.
SCRIPT_DIR = Path(__file__).resolve().parent       # scripts/
PROJECT_ROOT = SCRIPT_DIR.parent                    # heritage-rag-agent/
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"        # data/raw/

# 혹시 data/raw 폴더가 아직 없다면 자동으로 만들어줘요. (setup_project_structure.py를
# 실행 안 했어도 오류 없이 동작하게 하기 위한 안전장치예요.)
DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------
# 1. 기본 설정값 모음
# ------------------------------------------------------------

# 목록조회 API의 기본 주소입니다.
# 뒤에 ?gung_number=숫자 만 붙이면 그 궁의 목록을 요청할 수 있어요.
BASE_URL = "https://www.heritage.go.kr/heri/gungDetail/gogungListOpenApi.do"

# 궁 번호(gung_number)와 실제 궁 이름을 연결해 둔 사전(딕셔너리)이에요.
# 이렇게 미리 만들어 두면, 나중에 "3번"이 아니라 "창경궁"이라고 바로 알아볼 수 있어요.
GUNG_NAME_MAP = {
    1: "경복궁",
    2: "창덕궁",
    3: "창경궁",
    4: "덕수궁",
    5: "종묘",
}


# ------------------------------------------------------------
# 2. API를 호출해서 XML 원문(문자열 그대로의 응답)을 받아오는 함수
# ------------------------------------------------------------
def fetch_gung_list_xml(gung_number):
    """
    지정한 궁 번호(gung_number)로 목록조회 API를 호출하고,
    응답으로 받은 XML을 '문자열' 그대로 반환하는 함수예요.
    """
    # requests.get()은 "이 주소로 데이터를 요청해줘"라는 뜻이에요.
    # params에 넣은 값은 자동으로 "?gung_number=3" 같은 형태로 주소 뒤에 붙어요.
    # headers는 "나는 일반 웹브라우저야"라고 알려주는 역할이에요.
    # 일부 사이트는 이 정보가 없으면 요청을 막기도 해서 안전하게 넣어 둬요.
    response = requests.get(
        BASE_URL,
        params={"gung_number": gung_number},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,  # 10초 안에 응답이 없으면 오류를 내고 멈추게 해서, 무한 대기를 막아줘요.
    )

    # 응답이 정상(상태 코드 200)인지 확인해요.
    # 200이 아니면(예: 404, 500) 예외를 발생시켜서 바로 문제를 알아챌 수 있게 해요.
    response.raise_for_status()

    # 한글이 깨지지 않도록 인코딩을 utf-8로 명확히 지정해요.
    response.encoding = "utf-8"

    return response.text  # 응답 본문(XML 글자들)을 그대로 돌려줘요.


# ------------------------------------------------------------
# 3. XML 문자열을 분석해서, 우리가 원하는 값만 뽑아내는 함수
# ------------------------------------------------------------
def parse_gung_list_xml(xml_text, gung_number):
    """
    XML 문자열을 받아서, <list> 태그 하나하나(유산 하나하나)를
    파이썬 딕셔너리로 바꾸고, 그 딕셔너리들을 리스트에 담아 반환해요.
    """
    # 문자열을 파이썬이 다룰 수 있는 '트리(나무)' 구조로 변환해요.
    # 예: <result><list>...</list><list>...</list></result> 를
    #     "가지에 가지가 붙은 구조"로 바꿔서 원하는 태그를 쉽게 찾게 해줘요.
    root = ET.fromstring(xml_text)

    items = []  # 결과를 담을 빈 리스트를 준비해요.

    # root 바로 아래에 있는 <list> 태그를 하나씩 꺼내면서 반복해요.
    # 실제 응답에서 유산 하나하나가 <list> 태그로 감싸져 있었어요.
    for list_tag in root.findall("list"):

        # 태그 안의 글자를 안전하게 꺼내는 작은 도우미 함수예요.
        # CDATA로 감싸진 내용도 ElementTree가 자동으로 순수한 글자만 꺼내줘요.
        # 다만 " 홍화문 "처럼 앞뒤에 공백이 섞여 있어서 .strip()으로 제거해요.
        def get_text(tag_name):
            tag = list_tag.find(tag_name)
            # 태그 자체가 없거나 내용이 비어 있는 경우를 대비해 빈 문자열로 처리해요.
            if tag is None or tag.text is None:
                return ""
            return tag.text.strip()

        item = {
            "gung_number": gung_number,                        # 궁 번호 (요청할 때 넣은 값)
            "gung_name": GUNG_NAME_MAP.get(gung_number, ""),    # 궁 이름 (위 사전에서 찾아옴)
            "serial_number": get_text("serial_number"),         # 순번(키값)
            "detail_code": get_text("detail_code"),              # 세부코드 (상세조회에 필요)
            "contents_kor": get_text("contents_kor"),            # 국가유산명
            "explanation_kor": get_text("explanation_kor"),      # 국가유산 설명
            "img_url": get_text("imgUrl"),                       # 이미지 경로
            "detail_link": get_text("link"),                     # 상세조회 API 주소 (응답에 이미 포함되어 있어요!)
        }
        items.append(item)

    return items


# ------------------------------------------------------------
# 4. 전체 실행 흐름 (메인 함수)
# ------------------------------------------------------------
def main():
    all_items = []  # 5개 궁의 모든 유산 정보를 하나로 모을 리스트예요.

    # 1번(경복궁)부터 5번(종묘)까지 순서대로 호출해요.
    # range(1, 6)은 1, 2, 3, 4, 5를 의미해요 (6은 포함되지 않아요).
    for gung_number in range(1, 6):
        gung_name = GUNG_NAME_MAP[gung_number]
        print(f"[{gung_number}] {gung_name} 목록을 요청하는 중...")

        try:
            # ① API 호출해서 XML 받아오기
            xml_text = fetch_gung_list_xml(gung_number)

            # ② XML을 파싱해서 딕셔너리 리스트로 바꾸기
            items = parse_gung_list_xml(xml_text, gung_number)

            print(f"    -> {len(items)}건 수집 완료")
            all_items.extend(items)  # 전체 리스트에 이번 궁의 결과를 이어 붙여요.

        except requests.exceptions.RequestException as e:
            # 네트워크 오류(인터넷 연결 문제, 응답 지연 등)가 나면 여기서 잡아요.
            print(f"    ! {gung_name} 요청 중 오류 발생: {e}")

        except ET.ParseError as e:
            # 받은 응답이 XML 형식이 아니거나 중간에 깨져 있으면 여기서 잡아요.
            print(f"    ! {gung_name} XML 파싱 오류: {e}")

        # 공공 API 서버에 너무 짧은 간격으로 요청을 연달아 보내지 않도록 잠깐 쉬어요.
        time.sleep(0.5)

    # ------------------------------------------------------------
    # 5. 모은 데이터를 표(DataFrame)로 만들고 CSV로 저장하기
    # ------------------------------------------------------------
    df = pd.DataFrame(all_items)  # 딕셔너리들의 리스트를 표 형태로 바꿔줘요.

    # encoding="utf-8-sig"로 저장하면 엑셀에서 열었을 때 한글이 깨지지 않아요.
    output_path = DATA_RAW_DIR / "heritage_gung_list.csv"
    df.to_csv(output_path, index=False, encoding="utf-8-sig")

    print(f"\n총 {len(df)}건을 {output_path} 파일로 저장했습니다.")


# 이 파일을 "직접" 실행했을 때만 main()을 실행하라는 뜻이에요.
# (나중에 이 파일을 다른 코드에서 불러다 쓸 때는 main()이 자동 실행되지 않게 해줘요.)
if __name__ == "__main__":
    main()
