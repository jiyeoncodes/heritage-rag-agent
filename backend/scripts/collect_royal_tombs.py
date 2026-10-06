# collect_royal_tombs.py
# ------------------------------------------------------------
# 국가유산청 "국가유산 종합 Open API"에서 아래 세 가지를 수집하는 스크립트예요. (총 24건)
#   ① 조선왕릉 18개 능역(사적)   ② 경희궁지(사적 제271호)   ③ 5대 궁궐 개요 5건(경복궁·창덕궁·창경궁·덕수궁·종묘)
#
# 왜 필요한가?
#   기존 궁궐 API(collect_gung_*.py)는 "건물 단위" 해설만 있어서
#     - 경희궁과 왕릉이 없고,
#     - "창덕궁은 언제 지어졌어?" 처럼 궁궐 "전체"를 묻는 질문에 답할 자료도 없어요.
#   이 스크립트로 부족한 데이터를 채워요.
#
# 처리 흐름 (기존 궁궐 수집과 같은 "목록 → 상세" 2단계)
#   1) 목록조회: 사적(ccbaKdcd=13)에서 "릉" / "경희궁" / 5대 궁궐 이름으로 검색해요.
#      → 신라·고려 왕릉이 섞여 있으므로, 아래 이름 목록(ROYAL_TOMB_NAMES 등)과 "정확히 같은 이름"만 골라요.
#   2) 상세조회: 골라낸 건마다 상세 API를 호출해 설명글·소재지·이미지 등을 받아요.
#   3) 저장: 원본 XML은 data/raw/royal_xml/ 에, 표(CSV)는 data/raw/heritage_royal_tombs_detail.csv 에 저장해요.
#
# 실행 방법 (backend/scripts 폴더에서):  python collect_royal_tombs.py
# 인증키는 필요 없어요. 몇 번을 다시 실행해도 안전해요(같은 파일을 덮어쓸 뿐).
#
# ⚠ 이 스크립트는 작성자(Claude)가 실제 서버에 연결해 실행해 보지 못했어요.
#    (응답 모양을 흉내 낸 가짜 XML로 파싱·필터·저장 로직만 확인함. 단, 조선왕릉 18건 + 경희궁지는 사용자 PC에서
#     실제로 실행해 성공한 적이 있어요. 5대 궁궐 개요 5건은 아직 실제 실행 전이에요.)
# ------------------------------------------------------------

import hashlib                       # 설명글이 바뀌었는지 비교하기 위한 "지문(해시)"을 만드는 라이브러리
import time                          # 요청 사이에 잠깐 쉬기 위한 라이브러리
import xml.etree.ElementTree as ET   # XML 문자열을 분석(파싱)하는 라이브러리
from pathlib import Path             # 운영체제에 상관없이 경로를 다루는 라이브러리

import pandas as pd                  # 표 데이터를 다루고 CSV로 저장하는 라이브러리
import requests                      # 웹 API에 요청을 보내는 라이브러리


# ------------------------------------------------------------
# 0. 경로 설정 (다른 스크립트와 같은 방식: 이 파일 위치를 기준으로 계산)
# ------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent         # backend/scripts/
PROJECT_ROOT = SCRIPT_DIR.parent                      # backend/
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"          # backend/data/raw/
XML_DIR = DATA_RAW_DIR / "royal_xml"                  # 원본 XML 보관 폴더
OUTPUT_CSV = DATA_RAW_DIR / "heritage_royal_tombs_detail.csv"
XML_DIR.mkdir(parents=True, exist_ok=True)            # 폴더가 없으면 자동 생성


# ------------------------------------------------------------
# 1. 설정값
# ------------------------------------------------------------
LIST_URL = "https://www.khs.go.kr/cha/SearchKindOpenapiList.do"     # 목록조회
DETAIL_URL = "https://www.khs.go.kr/cha/SearchKindOpenapiDt.do"     # 상세조회
KIND_CODE_SAJEOK = "13"      # 종목 코드 13 = 사적
PAGE_UNIT = 100              # 목록을 한 번에 가져올 건수 ("릉" 검색 결과가 66건이라 한 번에 충분)

# 수집할 대상의 "이름 → 우리가 붙일 분류". 이름은 목록조회 응답의 ccbaMnm1 과 글자 그대로 같아야 해요.
# 왜 이름 목록(화이트리스트)으로 고르나?  "릉" 검색 결과에는 신라·백제·고려 왕릉(경주 무열왕릉 등)이
# 섞여 있어서, "릉이 들어간 것 전부"를 가져오면 조선왕릉이 아닌 것이 같이 들어와요.
ROYAL_TOMB_NAMES = [
    "구리 동구릉", "서울 헌릉과 인릉", "여주 영릉과 영릉", "영월 장릉", "남양주 광릉", "고양 서오릉",
    "서울 선릉과 정릉", "고양 서삼릉", "서울 태릉과 강릉", "김포 장릉", "파주 장릉", "서울 의릉",
    "파주 삼릉", "화성 융릉과 건릉", "남양주 홍릉과 유릉", "서울 정릉", "남양주 사릉", "양주 온릉",
]
GYEONGHUIGUNG_NAME = "경희궁지"          # 경희궁 (사적 제271호)
GYEONGHUIGUNG_QUERY = "경희궁"           # 목록에서 찾을 검색어

# 5대 궁궐 개요: 궁궐 "전체"를 설명하는 항목이에요. (건물 단위 해설은 기존 궁궐 API에 있어요.)
# 이름은 목록조회 응답의 ccbaMnm1 과 글자 그대로 같아야 해요. (종묘도 사적 제125호로 "종묘"라는 이름이에요.)
PALACE_OVERVIEW_NAMES = ["경복궁", "창덕궁", "창경궁", "덕수궁", "종묘"]
OVERVIEW_DISPLAY_NAME = "개요"           # DB의 유산명(contents_kor)에 넣을 이름. 출처 표시가 "[창덕궁 개요]" 처럼 깔끔해져요.

# 대상 종류별로 DB에 넣을 "분류명(gung_name)"과 "유산 유형(heritage_type)"을 정해 둬요.
GROUP_TOMB = "조선왕릉"
GROUP_GYEONGHUIGUNG = "경희궁"
GROUP_OVERVIEW = "궁궐 개요"
TYPE_TOMB = "능역"
TYPE_OVERVIEW = "개요"

# 상세 응답에서 꺼낼 필드: {CSV 컬럼 이름: XML 태그 이름}
DETAIL_FIELDS = {
    "name_kor": "ccbaMnm1",        # 국가유산명 (한글)
    "name_hanja": "ccbaMnm2",      # 국가유산명 (한자)
    "kind_name": "ccmaName",       # 종목 (사적)
    "category_mid": "mcodeName",   # 중분류 (예: 왕실무덤, 궁궐·관아)
    "category_small": "scodeName", # 소분류
    "area": "ccbaQuan",            # 면적
    "designated_date": "ccbaAsdt", # 지정일 (예: 19700526)
    "sido_name": "ccbaCtcdNm",     # 시도
    "sigungu_name": "ccsiName",    # 시군구
    "address": "ccbaLcad",         # 소재지
    "era": "ccceName",             # 시대
    "owner": "ccbaPoss",           # 소유자
    "admin": "ccbaAdmin",          # 관리자
    "longitude": "longitude",      # 경도
    "latitude": "latitude",        # 위도
    "img_url": "imageUrl",         # 대표 이미지
    "content": "content",          # ★ 설명글 (RAG에 쓸 본문)
}


# ------------------------------------------------------------
# 2. 공통 함수: 서버에 요청하고 XML 문자열을 받아오기 (실패하면 최대 3번 재시도)
# ------------------------------------------------------------
def fetch_xml(url, params, retries=3):
    """
    url에 params(조회 조건)를 붙여 요청하고, 응답 XML 문자열을 돌려줘요.
    일시적인 오류(서버 바쁨 등)에 대비해 실패하면 1초, 2초 쉬면서 최대 3번 시도해요.
    """
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            response.raise_for_status()      # 200(정상)이 아니면 예외 발생
            response.encoding = "utf-8"
            return response.text
        except requests.exceptions.RequestException as e:
            last_error = e
            print(f"    ! 요청 실패 ({attempt}/{retries}): {e}")
            time.sleep(attempt)              # 1초, 2초... 점점 더 오래 쉬었다가 재시도
    raise last_error                         # 3번 다 실패하면 마지막 오류를 그대로 던져요.


def text_of(parent, tag):
    """parent 아래에서 tag 이름의 태그를 찾아 글자만 꺼내요. 없거나 비었으면 빈 문자열."""
    node = parent.find(f".//{tag}")
    if node is None or node.text is None:
        return ""
    return node.text.strip()


# ------------------------------------------------------------
# 3. 목록조회: 이름으로 검색해서 {이름, 지정번호, 시도코드} 목록 만들기
# ------------------------------------------------------------
def parse_list_xml(xml_text):
    """목록 XML에서 <item> 하나하나를 딕셔너리로 바꿔 리스트로 돌려줘요."""
    root = ET.fromstring(xml_text)
    items = []
    for item in root.findall(".//item"):
        items.append({
            "name_kor": text_of(item, "ccbaMnm1"),   # 이름
            "asno": text_of(item, "ccbaAsno"),       # 지정번호 (13자리 그대로 써야 함!)
            "ctcd": text_of(item, "ccbaCtcd"),       # 시도 코드
        })
    return items


def search_list(query):
    """이름(query)으로 사적 목록을 검색해요. 결과가 PAGE_UNIT보다 많으면 다음 쪽도 가져와요."""
    results, page = [], 1
    while True:
        xml_text = fetch_xml(LIST_URL, {
            "ccbaKdcd": KIND_CODE_SAJEOK, "ccbaMnm1": query,
            "pageUnit": PAGE_UNIT, "pageIndex": page,
        })
        items = parse_list_xml(xml_text)
        results.extend(items)
        if len(items) < PAGE_UNIT:           # 한 쪽을 다 못 채웠으면 마지막 쪽이에요.
            return results
        page += 1
        time.sleep(0.3)


def make_target(group, gung_name, heritage_type, display_name, item):
    """수집 대상 1건의 정보를 한 묶음(딕셔너리)으로 만들어요."""
    return {"group": group, "gung_name": gung_name, "heritage_type": heritage_type,
            "display_name": display_name, "item": item}


def select_targets():
    """
    목록조회 결과에서 수집할 대상을 골라 리스트로 돌려줘요. 못 찾은 이름은 경고로 알려줘요.
      ① "릉" 검색 → 조선왕릉 18건     ② "경희궁" 검색 → 경희궁지
      ③ 5대 궁궐 이름 검색 → 이름이 정확히 같은 항목 5건 (개요)
    """
    targets = []

    # ① 조선왕릉
    tomb_items = search_list("릉")
    by_name = {it["name_kor"]: it for it in tomb_items}     # 이름으로 빨리 찾도록 사전으로 변환
    print(f"'릉' 검색 결과 {len(tomb_items)}건 중 조선왕릉만 골라요...")
    for name in ROYAL_TOMB_NAMES:
        if name in by_name:
            targets.append(make_target(GROUP_TOMB, GROUP_TOMB, TYPE_TOMB, name, by_name[name]))
        else:
            print(f"  ※ 목록에서 못 찾음: {name}  (이름이 바뀌었는지 확인이 필요해요)")

    # ② 경희궁지
    gh = [it for it in search_list(GYEONGHUIGUNG_QUERY) if it["name_kor"] == GYEONGHUIGUNG_NAME]
    if gh:
        targets.append(make_target(GROUP_GYEONGHUIGUNG, "경희궁", TYPE_OVERVIEW, GYEONGHUIGUNG_NAME, gh[0]))
    else:
        print(f"  ※ 목록에서 못 찾음: {GYEONGHUIGUNG_NAME}")

    # ③ 5대 궁궐 개요: 궁 이름으로 검색하면 "경복궁"을 포함한 다른 항목이 같이 나올 수 있어서 이름이 똑같은 것만 골라요.
    for name in PALACE_OVERVIEW_NAMES:
        found = [it for it in search_list(name) if it["name_kor"] == name]
        if found:
            # gung_name은 궁 이름 그대로(경복궁 등). 건물 항목(기존 데이터)과는 heritage_type으로 구분해요.
            targets.append(make_target(GROUP_OVERVIEW, name, TYPE_OVERVIEW, OVERVIEW_DISPLAY_NAME, found[0]))
        else:
            print(f"  ※ 목록에서 못 찾음: {name} (개요)")

    return targets


# ------------------------------------------------------------
# 4. 상세조회: 설명글 등을 받아 딕셔너리로 만들기
# ------------------------------------------------------------
def parse_detail_xml(xml_text):
    """상세 XML에서 DETAIL_FIELDS에 적은 필드를 꺼내 딕셔너리로 돌려줘요."""
    root = ET.fromstring(xml_text)
    return {col: text_of(root, tag) for col, tag in DETAIL_FIELDS.items()}


def collect_one(target):
    """대상 1건의 상세조회 → 원본 XML 저장 → 딕셔너리 반환. 응답이 비었으면 예외를 던져요."""
    item = target["item"]
    xml_text = fetch_xml(DETAIL_URL, {
        "ccbaKdcd": KIND_CODE_SAJEOK,
        "ccbaAsno": item["asno"],      # ⚠ 목록에서 받은 13자리 값을 그대로! (8자리로 줄이면 빈 응답이 와요)
        "ccbaCtcd": item["ctcd"],
    })

    # 원본 XML을 그대로 보관해요 (원본 보존 원칙). 나중에 다른 필드가 필요해도 다시 호출하지 않아도 돼요.
    (XML_DIR / f"{item['asno']}.xml").write_text(xml_text, encoding="utf-8")

    detail = parse_detail_xml(xml_text)

    # 안전장치: 이름이나 설명글이 비어 있으면 "오류 없이 빈 응답이 온" 경우예요. 조용히 넘기지 않고 실패로 처리해요.
    if not detail["name_kor"] or not detail["content"]:
        raise ValueError("상세 응답이 비어 있어요 (지정번호 형식을 확인하세요)")

    return {
        "group": target["group"],                  # 수집 묶음: 조선왕릉 / 경희궁 / 궁궐 개요
        "gung_name": target["gung_name"],          # DB 분류명 (조선왕릉 / 경희궁 / 경복궁 …)
        "heritage_type": target["heritage_type"],  # DB 유산 유형 (능역 / 개요)
        "display_name": target["display_name"],    # DB 유산명 (영월 장릉 / 경희궁지 / 개요)
        "ccba_asno": item["asno"],                 # 지정번호 (고유 키로 사용)
        "ccba_ctcd": item["ctcd"],
        **detail,                                  # kind_name(지정 종목: 사적)을 포함한 상세 필드들
        "content_length": len(detail["content"]),
        # 설명글의 "지문". 다음에 다시 수집했을 때 이 값이 같으면 "내용이 안 바뀜" → 다시 임베딩할 필요 없음.
        "content_hash": hashlib.sha256(detail["content"].encode("utf-8")).hexdigest()[:16],
    }


# ------------------------------------------------------------
# 5. 전체 실행 흐름
# ------------------------------------------------------------
def main():
    targets = select_targets()
    print(f"\n상세조회 대상: {len(targets)}건 (기대값: 조선왕릉 18 + 경희궁 1 + 궁궐 개요 5 = 24)\n")

    rows, failed = [], []
    for i, target in enumerate(targets, start=1):
        name = target["item"]["name_kor"]
        print(f"[{i}/{len(targets)}] {name} 상세조회 중...")
        try:
            rows.append(collect_one(target))
        except (requests.exceptions.RequestException, ET.ParseError, ValueError) as e:
            print(f"    ! 실패: {e}")
            failed.append((name, str(e)))
        time.sleep(0.3)                       # 서버에 부담 주지 않도록 쉬어가요.

    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")   # utf-8-sig: 엑셀에서도 한글이 안 깨져요.
    print(f"\n{len(df)}건을 {OUTPUT_CSV} 에 저장했어요.")
    if len(df):
        print(df.groupby("group")["content_length"].agg(["count", "min", "mean", "max"]).round(0))

    if failed:
        print(f"\n※ 실패 {len(failed)}건:")
        for name, msg in failed:
            print(f"   - {name}: {msg}")


if __name__ == "__main__":
    main()
