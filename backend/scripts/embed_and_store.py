# embed_and_store.py
# ------------------------------------------------------------
# 정리된 CSV 두 개를 읽어서, 설명글 원문(chunk_text = document_text에서 "[분류] 유산명 - " 머리말을 뗀 것)을
# Gemini 임베딩 API로 숫자 벡터로 바꾼 뒤,
# PostgreSQL(pgvector)의 v2 표(source, heritage, heritage_chunk, media)에 저장하는 스크립트입니다.
#   (v2에서는 유산 정보는 heritage(영어·일본어·중국어 이름도 name_en/name_ja/name_zh 컬럼에 같이 저장),
#    설명글+벡터는 heritage_chunk, 이미지·동영상은 media에 나눠 저장해요.)
#
#   - gung  : clean_gung_detail.py가 만든 heritage_gung_detail_clean.csv      (궁궐·종묘 127건)
#   - royal : clean_royal_tombs.py가 만든 heritage_royal_tombs_clean.csv      (조선왕릉 18 + 경희궁지 1 + 5대 궁궐 개요 5 = 24건)
#
# "이미 저장된 것"은 건너뛰어요 (여러 번 실행해도 안전):
#   - 궁궐: (궁 번호, 순번, 세부코드)가 이미 DB에 있으면 건너뜀
#   - 왕릉·경희궁·개요: (종목 코드 ccba_kdcd, 지정번호 ccba_asno)가 이미 DB에 있고 본문이 같으면 건너뜀,
#                  본문이 달라졌으면 다시 임베딩해서 그 행을 UPDATE (수정시간 updated_at은 DB가 자동 갱신)
#   ※ 지정번호만으로는 유일하지 않아요. 종목이 다르면 같은 번호가 있어서 종목 코드와 함께 비교해요.
#   ※ 건너뛴 행이라도 "임베딩이 필요 없는 정보"(외국어 이름, 시도 코드, 상위 유산 연결)는 매번 맞춰 줘요. (API 호출 없음)
#
# 실행 전 준비물 (반드시 순서대로!):
#   1) PostgreSQL + pgvector 서버가 켜져 있어야 해요
#   2) schema.sql(v2)을 실행해 표를 만들어 두고, v1 데이터가 있었다면 migrate_v1_to_v2.sql도,
#      heritage_alias 표가 이미 있는 DB라면 migrate_alias_to_heritage.sql도 실행해 둬야 해요
#   3) .env 파일에 GEMINI_API_KEY와 DB 접속 정보를 채워 둬야 해요
#   4) 아래 라이브러리를 설치해야 해요:
#      pip install google-genai psycopg2-binary python-dotenv pandas
#
# 실행 방법 (backend/scripts 폴더에서):
#   python embed_and_store.py              # 두 CSV 모두 (이미 저장된 건 알아서 건너뜀)
#   python embed_and_store.py --source royal   # 왕릉·경희궁만
#   python embed_and_store.py --source gung    # 궁궐·종묘만
# ------------------------------------------------------------

import argparse                              # 터미널에서 --source 같은 옵션을 받기 위한 라이브러리
import os
import hashlib                               # 본문이 바뀌었는지 비교할 해시(md5)를 만들기 위한 라이브러리
import re
import time
import pandas as pd
import psycopg2                                 # 파이썬에서 PostgreSQL에 접속하기 위한 라이브러리
from pathlib import Path                         # 운영체제에 상관없이 폴더 경로를 안전하게 다루는 라이브러리
from dotenv import load_dotenv                   # .env 파일을 읽어서 환경변수로 등록해주는 라이브러리
from google import genai                         # Gemini API를 호출하기 위한 라이브러리
from google.genai.types import EmbedContentConfig


# ------------------------------------------------------------
# 0. 폴더 구조에 맞는 경로 설정
# ------------------------------------------------------------

# 이 파일(embed_and_store.py)은 backend/scripts/ 폴더 안에 있다고 가정해요.
SCRIPT_DIR = Path(__file__).resolve().parent            # backend/scripts/
PROJECT_ROOT = SCRIPT_DIR.parent                         # backend/
DATA_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"  # 정리된 CSV가 있는 곳


# ------------------------------------------------------------
# 1. 환경변수(.env) 불러오기
# ------------------------------------------------------------
# .env 파일의 위치를 backend/ 폴더로 명확히 지정해요.
# override=True : 터미널에 같은 이름의 환경변수가 남아 있어도 항상 .env 값이 우선해요. (다른 스크립트와 같은 방식)
load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=True)

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]  # 키가 없으면 여기서 바로 오류가 나서, 문제를 빨리 알아챌 수 있어요.

# DB 접속 정보도 .env에서 가져와요. os.environ.get(이름, 기본값)은
# 해당 이름이 .env에 없을 때 기본값을 대신 쓰게 해줘요.
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5432"),
    "dbname": os.environ.get("DB_NAME", "postgres"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", "postgres"),
}

# 읽어올 CSV들 (이름 → 파일 경로)
INPUT_CSVS = {
    "gung": DATA_PROCESSED_DIR / "heritage_gung_detail_clean.csv",
    "royal": DATA_PROCESSED_DIR / "heritage_royal_tombs_clean.csv",
}

# 두 CSV의 모양을 맞춘 뒤 하나의 표로 합칠 때 쓰는 공통 컬럼들
COMMON_COLUMNS = [
    "gung_number", "gung_name", "serial_number", "detail_code",
    "ccba_kdcd", "ccba_asno", "ccba_ctcd",
    "contents_kor", "document_text", "img_url", "moving_urls",
    "heritage_type", "designation", "source",
    "name_en", "name_ja", "name_zh",        # 영어·일본어·중국어 이름 (heritage 표의 name_en/ja/zh 컬럼으로 들어가요)
]

# 궁궐·종묘 CSV에는 없는 값이라, 읽을 때 우리가 직접 채워 넣는 고정값들이에요.
GUNG_SOURCE = "국가유산청 궁궐·종묘 Open API"   # 출처
GUNG_HERITAGE_TYPE = "건물·시설"                 # 유산 유형 (궁궐 API는 건물·시설 단위 해설이에요)

# heritage_type(유산 유형) -> heritage_chunk.chunk_type(글 종류)
CHUNK_TYPE_BY_HERITAGE_TYPE = {"건물·시설": "건물 해설", "개요": "개요", "능역": "지정 설명"}

EMBEDDING_MODEL = "gemini-embedding-001"  # Gemini의 안정 버전 임베딩 모델 이름
EMBEDDING_DIM = 768                        # ⚠ schema.sql의 vector(768)과 반드시 똑같아야 해요!
BATCH_SIZE = 10                            # 한 번의 API 호출에 몇 개의 글을 같이 보낼지 (호출 횟수를 줄이기 위함)

# ▼ 429 오류(무료 한도 초과) 대응용 설정
# 무료 티어는 "1분에 100건"까지만 허용하고, 글 10개를 묶어 보내도 10건으로 세요!
# 그래서 배치 사이를 8초 쉬면 1분에 약 75건 → 한도(100건) 아래로 안전하게 유지돼요.
SLEEP_BETWEEN_BATCHES = 8   # 배치 사이 대기 시간(초)
MAX_RETRIES = 5              # 429가 나도 포기하지 않고 다시 시도할 최대 횟수
DEFAULT_WAIT = 60            # 오류 메시지에서 대기시간을 못 찾았을 때 쓸 기본 대기 시간(초)


# ------------------------------------------------------------
# 2. Gemini 클라이언트 준비
# ------------------------------------------------------------
client = genai.Client(api_key=GEMINI_API_KEY)


def embed_batch(texts):
    """
    글(문자열) 여러 개를 한 번의 API 호출로 임베딩(숫자 벡터로 변환)하는 함수예요.

    texts: 임베딩할 문자열들의 리스트 (예: ["설명1", "설명2", ...])
    반환값: 각 문자열에 대응하는 숫자 벡터들의 리스트
            (texts와 순서가 정확히 같아요. 1번째 글 -> 1번째 벡터)
    """
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=texts,
        config=EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT",       # "이 글들은 검색당할 문서다"라고 모델에 알려주는 설정이에요.
            output_dimensionality=EMBEDDING_DIM,  # 벡터의 차원 수를 pgvector 테이블과 맞춰요.
        ),
    )
    # response.embeddings는 texts와 같은 순서로 임베딩 결과를 담고 있어요.
    # 각 항목의 .values 안에 실제 숫자 리스트가 들어 있어요.
    return [item.values for item in response.embeddings]


def embed_with_retry(texts):
    """
    embed_batch()를 부르되, 429(한도 초과) 오류가 나면 잠깐 기다렸다가 다시 시도하는 함수예요.
    - 서버가 "13초 뒤에 다시 시도하세요"라고 알려주면 그 시간만큼 기다려요.
    - 그 안내가 없으면 기본 60초(=한도가 초기화되는 1분)를 기다려요.
    - 429가 아닌 다른 오류는 재시도하지 않고 바로 밖으로 던져요.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return embed_batch(texts)
        except Exception as e:
            msg = str(e)
            is_rate_limit = "429" in msg or "RESOURCE_EXHAUSTED" in msg
            # 한도 초과가 아니거나, 마지막 시도였다면 더 이상 재시도하지 않아요.
            if not is_rate_limit or attempt == MAX_RETRIES:
                raise
            # 오류 메시지 속 "Please retry in 13.80s" 에서 숫자만 뽑아내요.
            found = re.search(r"retry in ([\d.]+)s", msg)
            wait = float(found.group(1)) + 2 if found else DEFAULT_WAIT
            print(f"    ! 한도 초과(429). {wait:.0f}초 기다린 뒤 재시도해요... ({attempt}/{MAX_RETRIES})")
            time.sleep(wait)


def vector_to_pg_literal(vector):
    """
    파이썬의 숫자 리스트를 PostgreSQL의 vector 타입이 이해하는 문자열로 바꿔줘요.
    예: [0.1, 0.2, 0.3] -> "[0.1,0.2,0.3]"  (대괄호로 감싸고 쉼표로 이어 붙인 문자열)
    """
    return "[" + ",".join(str(v) for v in vector) + "]"


# ------------------------------------------------------------
# 3. CSV 읽기 → 공통 모양으로 맞추기
# ------------------------------------------------------------
def load_gung():
    """궁궐·종묘 CSV를 읽어 공통 컬럼 모양으로 돌려줘요. (ccba_asno는 없으니 빈 문자열)"""
    df = pd.read_csv(INPUT_CSVS["gung"], encoding="utf-8-sig")
    df["moving_urls"] = df["moving_urls"].fillna("")   # NaN(없음)을 그대로 DB에 넣으면 오류가 날 수 있어 미리 방지
    df["img_url"] = df["img_url"].fillna("")
    df["ccba_kdcd"] = ""                                 # 궁궐 API에는 종목 코드·지정번호·시도 코드가 없어요
    df["ccba_asno"] = ""
    df["ccba_ctcd"] = ""
    df["name_en"] = df["contents_eng"].fillna("")         # 영어·일본어·중국어 이름은 heritage 표의 name_en/ja/zh 컬럼에 저장해요
    df["name_ja"] = df["contents_jpa"].fillna("")
    df["name_zh"] = df["contents_chi"].fillna("")
    df["heritage_type"] = GUNG_HERITAGE_TYPE
    df["designation"] = ""                               # 궁궐 API에는 지정 종목 정보가 없어요 (DB에서는 NULL)
    df["source"] = GUNG_SOURCE
    return df[COMMON_COLUMNS]


def load_royal():
    """왕릉·경희궁 CSV를 읽어 공통 컬럼 모양으로 돌려줘요. (궁 번호·순번·세부코드는 없으니 빈 값)"""
    # dtype=str : 지정번호(0001930000000)의 앞자리 0이 사라지지 않도록 전부 문자열로 읽어요.
    df = pd.read_csv(INPUT_CSVS["royal"], encoding="utf-8-sig", dtype=str, keep_default_na=False)
    # 종목 코드·시도 코드는 clean_royal_tombs.py(최신)가 넣어 줘요. 옛 파일이면 안내하고 멈춰요.
    missing = [c for c in ("ccba_kdcd", "ccba_ctcd") if c not in df.columns]
    if missing:
        raise SystemExit(f"정리된 CSV에 {missing} 컬럼이 없어요 → clean_royal_tombs.py를 다시 실행하세요.")
    for col in ["gung_number", "serial_number", "detail_code"]:
        df[col] = None                                   # DB에서는 NULL(없음)이 돼요
    for col in ["name_en", "name_ja", "name_zh"]:
        df[col] = ""                                     # 이 데이터에는 외국어 이름이 없어요
    return df[COMMON_COLUMNS]   # heritage_type / designation / source 는 clean_royal_tombs.py가 CSV에 이미 넣어 뒀어요


# 한자만 들어 있는 괄호: "(御齋室)", "(正殿)" → 괄호 모양만 없애고 한자는 남겨요. ("(1865)", "(재위 1863∼1907)"은 한자가 없어서 그대로 둬요.)
HANJA_PAREN = re.compile(r"[(（]([\u4e00-\u9fff·\s]+)[)）]")


def normalize_text(text):
    """임베딩에 넣을 글을 가볍게 다듬어요. (원본 CSV는 그대로 두고, chunk_text에만 적용해요.)
       ① 줄바꿈 → 공백      ② 콜론(:, ：) → 공백      ③ 한자 괄호 "(御齋室)" → " 御齋室 "      ④ 겹친 공백 → 한 칸
    예) "어재실(御齋室) : 종묘의 ..." → "어재실 御齋室 종묘의 ..."
    ※ 글이 바뀌면 content_hash도 바뀌어서, embed_and_store.py가 알아서 다시 임베딩해요."""
    text = text.replace("\r\n", " ").replace("\n", " ")
    text = text.replace(":", " ").replace("：", " ")
    text = HANJA_PAREN.sub(r" \1 ", text)
    return re.sub(r"\s+", " ", text).strip()


def add_chunk_text(df):
    """CSV의 document_text("[분류] 유산명 - 설명글")에서 머리말을 떼어 "설명글(원문)"만 chunk_text 컬럼에 담아요.

    왜?  머리말("[경복궁]" 같은 분류 이름)은 같은 분류의 모든 글에 똑같이 붙어 있어서, 임베딩에 넣으면
         같은 분류의 글끼리 벡터가 비슷해지는 부작용이 있어요. 그래서 임베딩에는 원문만 넣고,
         머리말은 DB의 heritage.group_name / name_kor 컬럼에서 LLM에게 줄 때(rag.py) 다시 붙여요.
    안전장치: 머리말이 "[분류] 유산명 - " 모양이 아닌 행이 있으면 데이터가 이상한 거라서 멈춰요."""
    bodies = []
    for _, row in df.iterrows():
        header = f"[{row['gung_name']}] {row['contents_kor']} - "
        text = str(row["document_text"])
        if not text.startswith(header):
            raise SystemExit(f"머리말이 예상과 달라요: {text[:50]!r} (기대: {header!r}) → CSV를 확인하세요.")
        bodies.append(normalize_text(text[len(header):]))   # 머리말을 떼고 → 줄바꿈·콜론·한자괄호를 정리한 글
    df = df.copy()
    df["chunk_text"] = bodies
    return df


def to_int_or_none(value):
    """값이 비어 있으면 None(DB의 NULL), 숫자면 int로 바꿔 줘요."""
    if value is None or (not isinstance(value, str) and pd.isna(value)) or value == "":
        return None
    return int(value)


def str_or_none(value):
    """앞뒤 공백을 지우고, 비어 있으면(또는 NaN이면) None(DB의 NULL)으로 바꿔 줘요."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    value = str(value).strip()
    return value or None


def same_text(a, b):
    """두 본문이 같은지 비교해요. 줄바꿈 표기(\r\n/\n)나 앞뒤 공백 차이는 무시해요."""
    return (a or "").replace("\r\n", "\n").strip() == (b or "").replace("\r\n", "\n").strip()


def decide_actions(df, db_rows):
    """
    각 행이 DB에 대해 어떤 상태인지 판단해서 df에 "action" 컬럼을 붙여요.
      insert : DB에 없음 → 새로 저장
      update : DB에 있지만 본문(임베딩 입력)이 달라짐 → 다시 임베딩해서 갱신
      skip   : 이미 저장돼 있고 그대로 → 건너뜀

    db_rows: DB에서 읽어온 [(gung_number, serial_number, detail_code, ccba_kdcd, ccba_asno, chunk_text), ...]
    """
    gung_text = {(g, s, d): t for g, s, d, k, a, t in db_rows if a is None}      # (궁 번호, 순번, 세부코드) → 저장된 본문 (지정번호가 없는 행 = 궁궐 데이터)
    asno_text = {(k, a): t for _, _, _, k, a, t in db_rows if a is not None}     # (종목 코드, 지정번호) → 저장된 본문

    actions = []
    for _, row in df.iterrows():
        if row["ccba_asno"]:                               # 종합 API 데이터: (종목 코드, 지정번호)로 비교
            key = (row["ccba_kdcd"], row["ccba_asno"])
            if key not in asno_text:
                actions.append("insert")
            elif not same_text(asno_text[key], row["chunk_text"]):
                actions.append("update")
            else:
                actions.append("skip")
        else:                                              # 궁궐: (궁 번호, 순번, 세부코드)로 비교
            key = (int(row["gung_number"]), int(row["serial_number"]), int(row["detail_code"]))
            if key not in gung_text:
                actions.append("insert")
            elif not same_text(gung_text[key], row["chunk_text"]):   # 본문(임베딩 입력)이 바뀌었으면 다시 임베딩해요
                actions.append("update")
            else:
                actions.append("skip")
    df = df.copy()
    df["action"] = actions
    return df


# ------------------------------------------------------------
# 4. DB에 쓰기
# ------------------------------------------------------------
_source_ids = {}   # 출처 이름 -> source.id (같은 이름을 DB에서 여러 번 찾지 않으려는 메모)


def get_source_id(cur, name):
    """출처 이름으로 source.id를 찾아요. 없으면 새로 만들어요. (처음 보는 출처가 와도 멈추지 않게요)"""
    if name not in _source_ids:
        cur.execute(
            "INSERT INTO source (name) VALUES (%s) ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
            (name,),
        )
        _source_ids[name] = cur.fetchone()[0]
    return _source_ids[name]


def text_hash(text):
    """본문의 md5. DB의 md5(chunk_text)와 같은 값이에요. (둘 다 UTF-8 기준)"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def find_heritage_id(cur, row):
    """이 행에 해당하는 heritage.id를 찾아요. (없으면 None)"""
    if row["ccba_asno"]:
        cur.execute("SELECT id FROM heritage WHERE ccba_kdcd = %s AND ccba_asno = %s",
                    (row["ccba_kdcd"], row["ccba_asno"]))
    else:
        cur.execute("SELECT id FROM heritage WHERE gung_number = %s AND serial_number = %s AND detail_code = %s",
                    (to_int_or_none(row["gung_number"]), to_int_or_none(row["serial_number"]),
                     to_int_or_none(row["detail_code"])))
    found = cur.fetchone()
    return found[0] if found else None


def replace_media(cur, heritage_id, row):
    """이 유산의 이미지·동영상을 CSV 내용으로 맞춰요. (지우고 다시 넣는 방식이라 여러 번 해도 같아요)"""
    cur.execute("DELETE FROM media WHERE heritage_id = %s", (heritage_id,))
    img = (row["img_url"] or "").strip()
    if img:
        cur.execute("INSERT INTO media (heritage_id, media_type, url, sort_order) VALUES (%s, 'image', %s, 0) "
                    "ON CONFLICT (heritage_id, url) DO NOTHING", (heritage_id, img))
    videos = [u.strip() for u in (row["moving_urls"] or "").split(";") if u.strip()]
    for order, url in enumerate(videos):
        cur.execute("INSERT INTO media (heritage_id, media_type, url, sort_order) VALUES (%s, 'video', %s, %s) "
                    "ON CONFLICT (heritage_id, url) DO NOTHING", (heritage_id, url, order))


def insert_row(cur, row, embedding):
    """새 유산 한 건을 heritage + heritage_chunk + media에 저장해요. (등록시간은 DB가 자동으로 채워요)"""
    heritage_type = row["heritage_type"] or "건물·시설"
    cur.execute(
        """
        INSERT INTO heritage
            (ccba_kdcd, ccba_asno, ccba_ctcd, gung_number, serial_number, detail_code,
             group_name, name_kor, entity_type, designation, name_en, name_ja, name_zh)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            row["ccba_kdcd"] or None,        # 빈 문자열이면 NULL로 저장 (궁궐 데이터)
            row["ccba_asno"] or None,
            row["ccba_ctcd"] or None,
            to_int_or_none(row["gung_number"]),
            to_int_or_none(row["serial_number"]),
            to_int_or_none(row["detail_code"]),
            row["gung_name"],
            row["contents_kor"],
            heritage_type,
            row["designation"] or None,
            str_or_none(row["name_en"]),
            str_or_none(row["name_ja"]),
            str_or_none(row["name_zh"]),
        ),
    )
    heritage_id = cur.fetchone()[0]
    cur.execute(
        """
        INSERT INTO heritage_chunk
            (heritage_id, source_id, chunk_type, chunk_no, chunk_text, content_hash, embedding_model, embedding)
        VALUES (%s, %s, %s, 1, %s, %s, %s, %s::vector)
        """,
        (
            heritage_id,
            get_source_id(cur, row["source"]),
            CHUNK_TYPE_BY_HERITAGE_TYPE.get(heritage_type, "건물 해설"),
            row["chunk_text"],
            text_hash(row["chunk_text"]),
            EMBEDDING_MODEL,
            vector_to_pg_literal(embedding),
        ),
    )
    replace_media(cur, heritage_id, row)


def update_row(cur, row, embedding):
    """본문이 바뀐 종합 API 유산 한 건을 갱신해요. (수정시간 updated_at은 DB 트리거가 자동으로 갱신해요)"""
    heritage_id = find_heritage_id(cur, row)
    heritage_type = row["heritage_type"] or "건물·시설"
    cur.execute(
        """
        UPDATE heritage
           SET group_name = %s, name_kor = %s, entity_type = %s, designation = %s,
               ccba_ctcd = COALESCE(%s, ccba_ctcd),
               name_en = COALESCE(%s, name_en), name_ja = COALESCE(%s, name_ja), name_zh = COALESCE(%s, name_zh)
         WHERE id = %s
        """,
        (row["gung_name"], row["contents_kor"], heritage_type, row["designation"] or None,
         row["ccba_ctcd"] or None,
         str_or_none(row["name_en"]), str_or_none(row["name_ja"]), str_or_none(row["name_zh"]),
         heritage_id),
    )
    cur.execute(
        """
        UPDATE heritage_chunk
           SET source_id = %s, chunk_type = %s, chunk_text = %s, content_hash = %s,
               embedding_model = %s, embedding = %s::vector
         WHERE heritage_id = %s AND chunk_no = 1
        """,
        (
            get_source_id(cur, row["source"]),
            CHUNK_TYPE_BY_HERITAGE_TYPE.get(heritage_type, "건물 해설"),
            row["chunk_text"], text_hash(row["chunk_text"]),
            EMBEDDING_MODEL, vector_to_pg_literal(embedding),
            heritage_id,
        ),
    )
    replace_media(cur, heritage_id, row)


def sync_without_embedding(cur, df):
    """
    임베딩(API 호출)이 필요 없는 정보를, 건너뛴 행까지 포함해 매번 맞춰 줘요.
      1) 시도 코드(ccba_ctcd): v1에서 옮긴 종합 API 행은 비어 있으니 CSV 값으로 채워요. (이미 있으면 그대로)
      2) 외국어 이름(name_en/name_ja/name_zh): 영어·일본어·중국어 이름을 채워요. (이미 값이 있으면 그대로)
      3) 상위 유산(parent_id): 건물·시설을 같은 분류명의 개요 행에 연결해요. (이미 있으면 그대로)
    반환값: (채운 시도 코드 수, 새로 채운 외국어 이름 수, 새로 연결한 상위 유산 수)
    """
    ctcd_filled = 0
    names_added = 0
    for _, row in df.iterrows():
        heritage_id = find_heritage_id(cur, row)
        if heritage_id is None:
            continue                                   # 임베딩 실패로 아직 저장 안 된 행은 다음 실행 때 처리돼요
        if row["ccba_asno"] and row["ccba_ctcd"]:
            cur.execute("UPDATE heritage SET ccba_ctcd = %s WHERE id = %s AND ccba_ctcd IS NULL",
                        (row["ccba_ctcd"], heritage_id))
            ctcd_filled += cur.rowcount
        for col in ("name_en", "name_ja", "name_zh"):
            name = str_or_none(row[col])
            if name:
                # col은 위 튜플에서만 오는 고정 이름이라(사용자 입력이 아니라서) 문자열로 붙여도 안전해요.
                cur.execute(f"UPDATE heritage SET {col} = %s WHERE id = %s AND {col} IS NULL", (name, heritage_id))
                names_added += cur.rowcount
    cur.execute(
        """
        UPDATE heritage b SET parent_id = p.id
          FROM heritage p
         WHERE b.entity_type = '건물·시설' AND p.entity_type = '개요'
           AND p.group_name = b.group_name AND b.parent_id IS NULL
        """
    )
    return ctcd_filled, names_added, cur.rowcount


# ------------------------------------------------------------
# 5. 전체 실행 흐름 (메인 함수)
# ------------------------------------------------------------
def main():
    # ① 어떤 CSV를 처리할지 터미널 옵션으로 받아요. (기본값 all = 둘 다)
    parser = argparse.ArgumentParser(description="정리된 CSV를 임베딩해서 v2 표(heritage, heritage_chunk 등)에 저장")
    parser.add_argument("--source", choices=["all", "gung", "royal"], default="all",
                        help="gung=궁궐·종묘, royal=조선왕릉·경희궁, all=둘 다(기본)")
    args = parser.parse_args()

    # ② 선택한 CSV를 읽어 하나의 표로 합쳐요.
    frames = []
    if args.source in ("all", "gung"):
        frames.append(load_gung())
    if args.source in ("all", "royal"):
        frames.append(load_royal())
    df = add_chunk_text(pd.concat(frames, ignore_index=True))   # 머리말을 뗀 원문 → chunk_text (이게 임베딩·저장됨)
    print(f"읽어온 데이터: {len(df)}건 (source={args.source})\n")

    # ③ PostgreSQL에 연결해요.
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # 이 실행의 기록을 ingest_run에 남겨요. (몇 건 저장/갱신/건너뜀/실패했는지)
    cur.execute("INSERT INTO ingest_run (scope) VALUES (%s) RETURNING id", (args.source,))
    run_id = cur.fetchone()[0]
    conn.commit()

    # ④ DB에 이미 있는 것과 비교해서, 새로 저장/갱신/건너뛸 행을 나눠요. (이어하기 기능)
    #    429로 중간에 멈춰도 다시 실행하면 처리 안 된 것만 이어서 해요.
    cur.execute(
        """
        SELECT h.gung_number, h.serial_number, h.detail_code, h.ccba_kdcd, h.ccba_asno, c.chunk_text
          FROM heritage h JOIN heritage_chunk c ON c.heritage_id = h.id AND c.chunk_no = 1
        """
    )
    df = decide_actions(df, cur.fetchall())
    counts = df["action"].value_counts().to_dict()
    print(f"새로 저장 {counts.get('insert', 0)}건 / 내용이 바뀌어 갱신 {counts.get('update', 0)}건 / "
          f"이미 저장돼 건너뜀 {counts.get('skip', 0)}건\n")

    todo = df[df["action"] != "skip"].reset_index(drop=True)   # 실제로 임베딩할 행들만
    done = {"insert": 0, "update": 0}
    failed_batches = []   # 끝까지 실패한 배치를 기록해서, 마지막에 알려줘요.

    # ⑤ BATCH_SIZE(10)개씩 묶어서 임베딩해요. (API 호출 횟수를 줄여 무료 한도를 아끼려고요.)
    for start in range(0, len(todo), BATCH_SIZE):
        batch_df = todo.iloc[start:start + BATCH_SIZE]
        texts = batch_df["chunk_text"].tolist()

        print(f"[{start + 1} ~ {start + len(batch_df)} / {len(todo)}] 임베딩 요청 중...")

        try:
            embeddings = embed_with_retry(texts)           # 이 배치를 한 번의 호출로 임베딩

            # 배치 안의 각 행과 임베딩 결과를 짝지어(zip) 하나씩 DB에 반영해요.
            batch_counts = {"insert": 0, "update": 0}
            for (_, row), embedding in zip(batch_df.iterrows(), embeddings):
                if row["action"] == "insert":
                    insert_row(cur, row, embedding)
                else:
                    update_row(cur, row, embedding)
                batch_counts[row["action"]] += 1

            conn.commit()    # 배치 단위로 확정해서, 중간에 오류가 나도 이전 배치는 안전하게 남겨요.
            for k in done:   # 커밋까지 성공한 뒤에만 개수에 더해요.
                done[k] += batch_counts[k]

        except Exception as e:
            print(f"    ! 오류 발생: {e}")
            conn.rollback()  # 이 배치만 취소해서 DB를 깨끗하게 유지해요.
            failed_batches.append(f"{start + 1}~{start + len(batch_df)}")

        time.sleep(SLEEP_BETWEEN_BATCHES)   # 무료 한도(1분 100건)를 지키려고 배치 사이에 쉬어요.

    # ⑥ 임베딩이 필요 없는 정보(시도 코드, 외국어 이름, 상위 유산)를 맞추고, 실행 기록을 마무리해요.
    ctcd_filled, names_added, parent_linked = sync_without_embedding(cur, df)
    cur.execute(
        """
        UPDATE ingest_run
           SET finished_at = now(), inserted = %s, updated = %s, skipped = %s, failed_batches = %s, note = %s
         WHERE id = %s
        """,
        (done["insert"], done["update"], counts.get("skip", 0), len(failed_batches),
         f"시도 코드 {ctcd_filled}건 채움 / 외국어 이름 {names_added}건 채움 / 상위 유산 {parent_linked}건 연결", run_id),
    )
    conn.commit()
    print(f"\n임베딩 없이 맞춘 정보: 시도 코드 {ctcd_filled}건 / 외국어 이름 {names_added}건 / 상위 유산 연결 {parent_linked}건")

    cur.close()
    conn.close()

    print(f"\n이번 실행 결과: 새로 저장 {done['insert']}건, 갱신 {done['update']}건")
    if failed_batches:
        print(f"실패한 구간: {failed_batches} → 스크립트를 다시 실행하면 이 부분만 이어서 처리해요.")


if __name__ == "__main__":
    main()
