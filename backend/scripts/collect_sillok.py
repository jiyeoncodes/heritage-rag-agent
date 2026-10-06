# collect_sillok.py
# ------------------------------------------------------------
# 조선왕조실록 XML(공공데이터포털에서 받은 파일)에서 "궁궐·종묘·왕릉" 이야기가 나오는 기사만 골라내는 스크립트예요.
#
# 왜 필요한가?
#   - 실록은 태조~철종(+고종·순종)까지 기사가 수십만 건이라 전부 DB에 넣을 수 없어요.
#     (Gemini 임베딩 무료 한도가 하루 약 1,000회라서, 전부 넣으면 몇 달이 걸려요.)
#   - 그래서 "경복궁, 창덕궁, 영릉(세종 능) …"처럼 우리 프로젝트의 문화유산 이름이 나오는 기사만 먼저 모아요.
#   - 이 기사들은 나중에 3단계(관계 탐색)에서 "어떤 인물이 어떤 유산과 연결되는지"의 근거 문장으로 쓰여요.
#
# 이 스크립트는 "다운로드"는 하지 않아요.  (공공데이터포털은 로그인/버튼 클릭이 필요해서 직접 받아야 해요.)
#   ① 공공데이터포털에서 아래 두 데이터셋을 내려받아요.
#        - 교육부 국사편찬위원회_조선왕조실록 정보_실록원문  (태조~철종실록, XML)
#        - 교육부 국사편찬위원회_조선왕조실록 정보_고순종실록 원문  (고종·순종실록, XML)
#      (라이선스: 공공누리 1유형 = 출처만 표시하면 되고, 인공지능 학습용으로도 허용된다고 적혀 있어요.)
#   ② 받은 .xml 또는 .zip 파일을 backend/data/raw/sillok_xml/ 폴더에 그대로 넣어요. (압축을 풀지 않아도 돼요!)
#   ③ backend 폴더에서 실행해요:   python scripts\collect_sillok.py
#
# 처리 흐름
#   1) sillok_xml/ 안의 모든 .xml / .zip 을 찾아요. (원본 파일은 절대 수정하지 않아요 = 원본 보존)
#   2) 파일마다 XML을 읽어서 "기사(id 가 waa_10201006_001 모양인 것)"를 하나씩 꺼내요.
#   3) 기사 본문에 우리 키워드(한글 + 한자)가 있으면 "선택"해요.
#   4) 선택된 기사를 표(CSV)와 원본 XML 조각(JSONL)으로 저장해요.
#
# 결과 파일 (모두 backend/data/raw/ 안)
#   - sillok_heritage_articles.csv   : 선택된 기사 표 (RAG/관계 추출에 쓸 본문)
#   - sillok_heritage_articles.jsonl : 선택된 기사의 원본 XML 조각 (나중에 다른 정보가 필요할 때 다시 쓰려고 보관)
#   - sillok_keyword_summary.csv     : 키워드별로 기사가 몇 건 걸렸는지 (너무 많은 키워드를 찾아내는 용도)
#
# ⚠ 검증 상태: 작성자(Claude)는 실제 실록 XML 파일을 받아 보지 못했어요.
#    공개된 구조 설명(level1~level5, id 규칙, <paragraph>, <index>)을 바탕으로 만든 "가짜 XML"로만 시험했어요.
#    실제 파일에서 기사가 0건으로 나오면 스크립트가 태그 이름 몇 개를 보여주니, 그 출력만 알려 주세요.
# ------------------------------------------------------------

import argparse                       # 명령줄 옵션(--groups 등)을 받는 라이브러리
import hashlib                        # 본문이 바뀌었는지 비교하는 "지문(해시)"을 만드는 라이브러리
import json                           # 원본 XML 조각을 JSONL로 저장하기 위한 라이브러리
import re                             # 글자 패턴(정규식)으로 id를 해석하는 라이브러리
import zipfile                        # .zip 파일을 풀지 않고 안의 XML을 바로 읽는 라이브러리
import xml.etree.ElementTree as ET    # XML 문자열을 분석(파싱)하는 라이브러리
from collections import Counter       # 개수를 세는 도구
from pathlib import Path              # 운영체제에 상관없이 경로를 다루는 라이브러리

import pandas as pd                   # 표 데이터를 다루고 CSV로 저장하는 라이브러리


# ------------------------------------------------------------
# 0. 경로 설정 (다른 스크립트와 같은 방식: 이 파일 위치를 기준으로 계산)
# ------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent          # backend/scripts/
PROJECT_ROOT = SCRIPT_DIR.parent                       # backend/
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"           # backend/data/raw/
DEFAULT_INPUT_DIR = DATA_RAW_DIR / "sillok_xml"        # 내려받은 원본 XML/ZIP을 넣어 두는 폴더
OUTPUT_CSV = DATA_RAW_DIR / "sillok_heritage_articles.csv"
OUTPUT_JSONL = DATA_RAW_DIR / "sillok_heritage_articles.jsonl"
OUTPUT_SUMMARY = DATA_RAW_DIR / "sillok_keyword_summary.csv"


# ------------------------------------------------------------
# 1. 찾을 키워드 목록
# ------------------------------------------------------------
# 구조: (묶음, 대표 이름, [실제로 찾을 글자들])
#   - 공공데이터포털의 "실록원문"은 한문(한자)이라서, 한글 이름과 한자 이름을 "둘 다" 찾아요.
#   - 같은 한글 이름이 여러 능을 가리키는 경우가 있어요. 예) 장릉 = 莊陵(단종) / 長陵(인조) / 章陵(원종)
#     → 한 대표 이름 아래에 한자를 모두 적어 두었어요. (어느 능인지는 나중에 한자로 구분할 수 있어요.)
#   - 시대에 따라 이름이 바뀐 궁도 같이 적었어요. 예) 경희궁 = 경덕궁(慶德宮)이었다가 1760년에 개명
#   - ⚠ 한 글자짜리 단어(예: 陵)는 너무 많이 걸려서 일부러 뺐어요.
TARGETS = [
    # ── 궁궐 ──
    ("palace", "경복궁", ["경복궁", "景福宮"]),
    ("palace", "창덕궁", ["창덕궁", "昌德宮"]),
    ("palace", "창경궁", ["창경궁", "昌慶宮", "수강궁", "壽康宮"]),   # 창경궁은 처음에 수강궁이라 불렸어요.
    ("palace", "덕수궁", ["덕수궁", "德壽宮", "경운궁", "慶運宮"]),   # ⚠ 조선 초기의 '덕수궁'은 상왕궁의 이름이라 지금의 덕수궁과 다를 수 있어요.
    ("palace", "경희궁", ["경희궁", "慶熙宮", "경덕궁", "慶德宮"]),
    # ── 종묘 ──
    ("shrine", "종묘", ["종묘", "宗廟", "영녕전", "永寧殿"]),
    # ── 왕릉 (능호 기준) ──
    ("tomb", "건원릉", ["건원릉", "健元陵"]),       # 태조
    ("tomb", "제릉", ["제릉", "齊陵"]),            # 신의왕후
    ("tomb", "후릉", ["후릉", "厚陵"]),            # 정종
    ("tomb", "헌릉", ["헌릉", "獻陵"]),            # 태종
    ("tomb", "영릉", ["영릉", "英陵", "寧陵", "永陵"]),  # 세종(英陵) / 효종(寧陵) / 진종(永陵)
    ("tomb", "현릉", ["현릉", "顯陵"]),            # 문종
    ("tomb", "장릉", ["장릉", "莊陵", "長陵", "章陵"]),  # 단종 / 인조 / 원종
    ("tomb", "광릉", ["광릉", "光陵"]),            # 세조
    ("tomb", "창릉", ["창릉", "昌陵"]),            # 예종
    ("tomb", "경릉", ["경릉", "敬陵", "景陵"]),      # 덕종 / 헌종
    ("tomb", "공릉", ["공릉", "恭陵"]),            # 장순왕후
    ("tomb", "순릉", ["순릉", "順陵"]),            # 공혜왕후
    ("tomb", "선릉", ["선릉", "宣陵"]),            # 성종
    ("tomb", "정릉", ["정릉", "靖陵", "貞陵"]),      # 중종 / 신덕왕후
    ("tomb", "효릉", ["효릉", "孝陵"]),            # 인종
    ("tomb", "강릉", ["강릉", "康陵"]),            # 명종   (⚠ 강원도 '강릉(江陵)'은 한자가 달라서 한자로만 구분돼요)
    ("tomb", "목릉", ["목릉", "穆陵"]),            # 선조
    ("tomb", "숭릉", ["숭릉", "崇陵"]),            # 현종
    ("tomb", "명릉", ["명릉", "明陵"]),            # 숙종
    ("tomb", "익릉", ["익릉", "翼陵"]),            # 인경왕후
    ("tomb", "의릉", ["의릉", "懿陵"]),            # 경종
    ("tomb", "홍릉", ["홍릉", "弘陵", "洪陵"]),      # 정성왕후 / 고종
    ("tomb", "원릉", ["원릉", "元陵"]),            # 영조
    ("tomb", "융릉", ["융릉", "隆陵"]),            # 장조(사도세자)
    ("tomb", "건릉", ["건릉", "健陵"]),            # 정조
    ("tomb", "인릉", ["인릉", "仁陵"]),            # 순조
    ("tomb", "수릉", ["수릉", "綏陵"]),            # 문조
    ("tomb", "예릉", ["예릉", "睿陵"]),            # 철종
    ("tomb", "유릉", ["유릉", "裕陵"]),            # 순종
    ("tomb", "사릉", ["사릉", "思陵"]),            # 정순왕후
    ("tomb", "온릉", ["온릉", "溫陵"]),            # 단경왕후
    ("tomb", "소릉", ["소릉", "昭陵"]),            # 현덕왕후
    ("tomb", "휘릉", ["휘릉", "徽陵"]),            # 장렬왕후
    ("tomb", "혜릉", ["혜릉", "惠陵"]),            # 단의왕후
    ("tomb", "동구릉", ["동구릉", "東九陵"]),
    ("tomb", "서오릉", ["서오릉", "西五陵"]),
    ("tomb", "서삼릉", ["서삼릉", "西三陵"]),
    # ── 왕릉 일반 용어 (능 이름이 안 나와도 왕릉 조성 이야기인 기사) ──
    ("tomb_general", "산릉", ["산릉", "山陵"]),
    ("tomb_general", "능침", ["능침", "陵寢"]),
    ("tomb_general", "천릉", ["천릉", "遷陵"]),
]
ALL_GROUPS = ["palace", "shrine", "tomb", "tomb_general"]


# ------------------------------------------------------------
# 2. XML 읽기 도우미 함수들
# ------------------------------------------------------------
# 기사 id 모양:  waa_10201006_001   (왕대 3글자 _ 날짜 8자리 _ 기사 순번 3자리)
ARTICLE_ID = re.compile(r"^[a-z]{3}_\d{8}_\d{3}$")
# 날짜 8자리 해석:  1 02 01 0 06  →  (재위년 앞자리) (재위년 2자리) (월) (윤달 표시) (일)
DATE_PART = re.compile(r"^(?P<code>[a-z]{3})_(?P<y1>\d)(?P<y2>\d{2})(?P<m>\d{2})(?P<leap>\d)(?P<d>\d{2})_(?P<seq>\d{3})$")
# 본문에서 빼고 읽을 태그: 주석(교감주 등)은 본문이 아니라서 제외해요.
SKIP_TAGS = {"annotation", "noteContent"}


def local(tag):
    """'{namespace}paragraph' 처럼 앞에 붙은 주소를 떼고 'paragraph' 만 돌려줘요."""
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def iter_text(elem):
    """
    elem 안의 글자를 순서대로 모아요. 주석(SKIP_TAGS)은 건너뛰지만,
    주석 "뒤에 이어지는 본문(tail)"은 놓치지 않고 읽어요.
    """
    if local(elem.tag) not in SKIP_TAGS and elem.text:
        yield elem.text
    for child in elem:
        if local(child.tag) not in SKIP_TAGS:
            yield from iter_text(child)
        if child.tail:
            yield child.tail


def article_text(article):
    """
    기사 1건의 본문을 문단별로 이어 붙여요.
    <paragraph> 가 있으면 문단 단위로, 없으면 <text> 전체(또는 기사 전체)에서 글자를 모아요.
    <front>(제목·메타데이터)는 본문이 아니라서 제외해요.
    """
    paragraphs = [e for e in article.iter() if local(e.tag) == "paragraph"]
    if paragraphs:
        lines = ["".join(iter_text(p)) for p in paragraphs]
    else:
        text_nodes = [e for e in article if local(e.tag) == "text"] or [article]
        lines = ["".join(iter_text(t)) for t in text_nodes]
    # 줄 안의 여러 공백/줄바꿈을 한 칸으로 정리하고, 빈 줄은 버려요.
    cleaned = [re.sub(r"\s+", " ", ln).strip() for ln in lines]
    return "\n".join(ln for ln in cleaned if ln)


def first_title(elem):
    """elem 안에서 처음 나오는 <mainTitle> 글자를 돌려줘요. 없으면 빈 문자열."""
    for e in elem.iter():
        if local(e.tag) == "mainTitle":
            return "".join(iter_text(e)).strip()
    return ""


def reign_title(root, fallback):
    """어느 왕의 실록인지(예: 태조실록) 알아내요. level1 의 제목 → 실패하면 파일 이름을 써요."""
    for e in root.iter():
        if local(e.tag) == "level1":
            t = first_title(e)
            if t:
                return t
    return fallback


# 기사 id 의 두 번째·세 번째 글자로 "어느 왕의 실록인지" 알 수 있어요.  예) wda_10101001_001 → w(원문) d(세종) a(본판)
#   두 번째 글자 = 왕,  세 번째 글자 = 판본 (a: 본판 / b: 수정·개수·정오·정초본 등 / c: 순종실록 부록)
#   (실제 실행 결과에서 왕별 최대 재위년과 맞는 것을 확인했어요. 예: 세종 d = 32년, 선조 n = 41년, 영조 u = 52년)
KING_BY_LETTER = {
    "a": "태조", "b": "정종", "c": "태종", "d": "세종", "e": "문종", "f": "단종", "g": "세조", "h": "예종",
    "i": "성종", "j": "연산군", "k": "중종", "l": "인종", "m": "명종", "n": "선조", "o": "광해군", "p": "인조",
    "q": "효종", "r": "현종", "s": "숙종", "t": "경종", "u": "영조", "v": "정조", "w": "순조", "x": "헌종", "y": "철종",
}


def king_name(article_id, fallback=""):
    """기사 id 에서 '세종실록', '광해군일기(정초본)' 같은 이름을 만들어요. 모르는 글자면 fallback 을 돌려줘요."""
    if len(article_id) < 3:
        return fallback
    king, ver = article_id[1], article_id[2]
    if king == "z":                                  # 고종·순종은 같은 글자(z)를 나눠 써요.
        return {"a": "고종실록", "b": "순종실록", "c": "순종실록부록"}.get(ver, fallback)
    name = KING_BY_LETTER.get(king)
    if not name:
        return fallback
    base = f"{name}일기" if king in ("j", "o") else f"{name}실록"   # 연산군·광해군은 '일기'
    if king == "o":
        return base + ("(중초본)" if ver == "a" else "(정초본)")
    return base + ("(수정·개수본)" if ver == "b" else "")


def parse_id(article_id):
    """id 에서 재위년·월·일을 꺼내요. 모양이 다르면 빈 값으로 돌려줘요."""
    m = DATE_PART.match(article_id)
    if not m:
        return {"regnal_year": "", "month": "", "leap_month": "", "day": ""}
    year = int(m["y1"] + m["y2"]) - 100          # 파일 이름 102 = 재위 2년  → 102 - 100 = 2
    return {
        "regnal_year": year if year > 0 else "",
        "month": int(m["m"]) or "",
        "leap_month": "Y" if m["leap"] != "0" else "",
        "day": int(m["d"]) or "",
    }


def language_of(text):
    """본문이 한글(국역)인지 한자(원문)인지 대충 판별해요. 한글이 20% 넘으면 'ko', 아니면 'hanja'."""
    if not text:
        return ""
    hangul = sum(1 for ch in text if "가" <= ch <= "힣")
    return "ko" if hangul / len(text) > 0.2 else "hanja"


# 긴 이름부터 먼저 찾기 위해, (찾을 글자, 대표 이름, 묶음)을 길이 순으로 미리 정렬해 둬요.
SORTED_VARIANTS = sorted(
    [(v, name, group) for group, name, variants in TARGETS for v in variants],
    key=lambda t: -len(t[0]),
)


def match_keywords(text, wanted_groups):
    """
    본문에서 키워드를 찾아요.  돌려주는 값: {대표이름: 묶음} 딕셔너리 (한 기사에 여러 개가 걸릴 수 있어요)

    왜 "긴 이름부터" 찾나?
      '건원릉(健元陵)' 안에는 '원릉(元陵, 영조의 능)'이 글자 그대로 들어 있어요.
      그냥 찾으면 건원릉 기사가 원릉 기사로도 잘못 집계돼요.
      그래서 긴 이름을 먼저 찾고, 찾은 자리는 지워 버린 뒤(\0) 짧은 이름을 찾아요.
    """
    found = {}
    work = text                                  # 원문은 그대로 두고, 지워 가며 쓸 복사본을 써요.
    for variant, name, group in SORTED_VARIANTS:
        if group not in wanted_groups:
            continue
        if variant in work:
            found[name] = group
            work = work.replace(variant, "\0" * len(variant))
    return found


# ------------------------------------------------------------
# 3. 입력 파일 찾기 (XML과 ZIP을 모두 지원)
# ------------------------------------------------------------
def iter_xml_sources(input_dir):
    """
    input_dir 아래의 모든 .xml 과 .zip 을 찾아서 (표시용 이름, XML 바이트) 를 하나씩 돌려줘요.
    ZIP 은 풀지 않고 안의 .xml 만 메모리에서 바로 읽어요 → 원본 ZIP 은 그대로 보존돼요.
    """
    for path in sorted(input_dir.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix == ".xml":
            yield path.name, path.read_bytes()
        elif suffix == ".zip":
            with zipfile.ZipFile(path) as zf:
                for member in sorted(zf.namelist()):
                    if member.lower().endswith(".xml"):
                        # 한글 파일명이 깨져 보일 수 있어서, 표시는 'zip이름::파일이름' 으로 해요.
                        yield f"{path.name}::{Path(member).name}", zf.read(member)


# XML 1.0 에서 "써도 되는 글자 번호" 범위. 이 밖의 번호를 &#...; 로 적어 두면 파서가 파일 전체를 거부해요.
#   (실제 실행에서 현종개수실록 104·105, 효종실록 106 이 'invalid character number' 로 실패했어요.)
CHAR_REF = re.compile(rb"&#(?:[xX]([0-9A-Fa-f]+)|([0-9]+));")


def _valid_xml_char(code):
    return (code in (0x9, 0xA, 0xD) or 0x20 <= code <= 0xD7FF
            or 0xE000 <= code <= 0xFFFD or 0x10000 <= code <= 0x10FFFF)


def drop_invalid_char_refs(xml_bytes):
    """
    XML 에서 허용되지 않는 글자 번호(&#...;)만 찾아서 지워요. 나머지 내용은 그대로예요.
    돌려주는 값: (고친 XML 바이트, 지운 개수)
    """
    removed = 0

    def fix(m):
        nonlocal removed
        code = int(m.group(1), 16) if m.group(1) else int(m.group(2))
        if _valid_xml_char(code):
            return m.group(0)          # 정상 글자 번호는 그대로 둬요.
        removed += 1
        return b""                     # 잘못된 번호는 지워요.

    return CHAR_REF.sub(fix, xml_bytes), removed


# ------------------------------------------------------------
# 4. 파일 1개 처리: 기사 꺼내기 → 키워드 걸러내기
# ------------------------------------------------------------
def process_source(source_name, xml_bytes, wanted_groups, keyword_counter, stats):
    """
    XML 한 파일에서 기사들을 꺼내 키워드가 있는 것만 (표 한 줄, 원본조각) 으로 돌려줘요.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as first_error:
        # 흔한 원인: 허용되지 않는 글자 번호(&#...;). 그것만 지우고 한 번 더 시도해요.
        fixed_bytes, removed = drop_invalid_char_refs(xml_bytes)
        try:
            root = ET.fromstring(fixed_bytes)
            print(f"  * 잘못된 글자 번호 {removed}개를 지우고 읽음: {source_name}")
            stats["repaired_files"] += 1
        except ET.ParseError as e:
            # 그래도 안 되면 전체가 멈추지 않도록, 경고만 남기고 다음 파일로 넘어가요.
            print(f"  ! XML 해석 실패, 건너뜀: {source_name}  ({first_error} / 재시도: {e})")
            stats["failed_files"] += 1
            return

    reign = reign_title(root, fallback=Path(source_name.split("::")[-1]).stem)
    articles = [e for e in root.iter() if ARTICLE_ID.match(e.get("id", "") or "")]

    if not articles:
        # 구조가 예상과 다르다는 신호예요. 사용자가 알려줄 수 있게 태그 이름 몇 개를 보여줘요.
        tags = sorted({local(e.tag) for e in root.iter()})[:15]
        print(f"  ! 기사를 찾지 못함: {source_name}  (태그 예시: {tags})")
        stats["no_article_files"] += 1
        return

    selected = 0
    for art in articles:
        stats["articles_total"] += 1
        text = article_text(art)
        if not text:
            continue
        found = match_keywords(text, wanted_groups)
        if not found:
            continue

        art_id = art.get("id")
        keyword_counter.update(found.keys())                 # 키워드별 기사 수 집계
        row = {
            "article_id": art_id,
            "reign_title": king_name(art_id, reign),
            **parse_id(art_id),
            "title": first_title(art),
            "text": text,
            "text_length": len(text),
            "language": language_of(text),
            "match_groups": ";".join(sorted(set(found.values()))),
            "matched_keywords": ";".join(sorted(found.keys())),
            "source_file": source_name,
            "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        }
        raw = ET.tostring(art, encoding="unicode")           # 이 기사의 원본 XML 조각
        yield row, raw
        selected += 1

    print(f"  - {source_name}: 기사 {len(articles):,}건 중 {selected:,}건 선택 ({reign})")
    stats["articles_selected"] += selected


# ------------------------------------------------------------
# 5. 전체 실행 흐름
# ------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="실록 XML에서 궁궐·종묘·왕릉 기사만 골라 저장")
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR), help="원본 XML/ZIP 폴더 (기본: data/raw/sillok_xml)")
    parser.add_argument("--groups", default=",".join(ALL_GROUPS),
                        help="찾을 묶음. 쉼표로 구분 (palace,shrine,tomb,tomb_general). 기본: 전부")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    wanted = {g.strip() for g in args.groups.split(",") if g.strip()}
    unknown = wanted - set(ALL_GROUPS)
    if unknown:
        raise SystemExit(f"알 수 없는 묶음: {sorted(unknown)}  (사용 가능: {ALL_GROUPS})")

    if not input_dir.exists() or not any(input_dir.rglob("*")):
        input_dir.mkdir(parents=True, exist_ok=True)
        raise SystemExit(
            f"\n원본 파일이 아직 없어요.\n"
            f"  1) 공공데이터포털에서 '조선왕조실록 정보_실록원문', '고순종실록 원문'을 내려받고\n"
            f"  2) 아래 폴더에 .xml 또는 .zip 을 그대로 넣은 뒤 다시 실행해 주세요.\n"
            f"     {input_dir}\n"
        )

    print(f"입력 폴더: {input_dir}")
    print(f"찾는 묶음: {sorted(wanted)}\n")

    keyword_counter = Counter()
    stats = Counter()
    rows = []

    # JSONL 은 한 줄에 기사 1건씩 적는 형식이라, 큰 데이터도 메모리를 아끼며 저장할 수 있어요.
    with open(OUTPUT_JSONL, "w", encoding="utf-8") as jf:
        for source_name, xml_bytes in iter_xml_sources(input_dir):
            stats["files"] += 1
            for row, raw in process_source(source_name, xml_bytes, wanted, keyword_counter, stats):
                rows.append(row)
                jf.write(json.dumps({"article_id": row["article_id"], "xml": raw}, ensure_ascii=False) + "\n")

    if not rows:
        print("\n선택된 기사가 0건이에요. 위의 경고 메시지(기사를 찾지 못함 등)를 확인해 주세요.")
        return

    df = pd.DataFrame(rows).drop_duplicates(subset="article_id")    # 같은 기사가 두 번 들어온 경우 하나만
    df = df.sort_values("article_id").reset_index(drop=True)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")        # utf-8-sig: 엑셀에서도 한글/한자가 안 깨져요.

    summary = (pd.DataFrame(sorted(keyword_counter.items(), key=lambda kv: -kv[1]), columns=["keyword", "article_count"]))
    group_of = {name: group for group, name, _ in TARGETS}
    summary.insert(1, "group", summary["keyword"].map(group_of))
    summary.to_csv(OUTPUT_SUMMARY, index=False, encoding="utf-8-sig")

    print("\n===== 결과 =====")
    print(f"읽은 파일 {stats['files']}개 (해석 실패 {stats['failed_files']}, 복구해서 읽음 {stats['repaired_files']}, 기사 없음 {stats['no_article_files']})")
    print(f"전체 기사 {stats['articles_total']:,}건 중 선택 {len(df):,}건")
    print(f"언어: {df['language'].value_counts().to_dict()}")
    print(f"묶음별: {df['match_groups'].value_counts().head(8).to_dict()}")
    print(f"본문 길이 평균 {df['text_length'].mean():.0f}자 / 최대 {df['text_length'].max():,}자")
    print(f"\n저장: {OUTPUT_CSV.name}, {OUTPUT_JSONL.name}, {OUTPUT_SUMMARY.name}  ({DATA_RAW_DIR})")
    print("키워드 상위 10:\n" + summary.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
