# embed_and_store.py
# ------------------------------------------------------------
# clean_gung_detail.py로 만든 heritage_gung_detail_clean.csv를 읽어서,
# document_text를 Gemini 임베딩 API로 숫자 벡터로 바꾼 뒤,
# PostgreSQL(pgvector)의 heritage_chunks 테이블에 저장하는 스크립트입니다.
#
# 실행 전 준비물 (반드시 순서대로!):
#   1) PostgreSQL + pgvector 서버가 켜져 있어야 해요
#   2) schema.sql을 실행해서 heritage_chunks 테이블을 미리 만들어 둬야 해요
#   3) .env 파일에 GEMINI_API_KEY와 DB 접속 정보를 채워 둬야 해요
#   4) 아래 라이브러리를 설치해야 해요:
#      pip install google-genai psycopg2-binary python-dotenv pandas
#
# 실행 방법: python embed_and_store.py
# ------------------------------------------------------------

import os
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

# 이 파일(embed_and_store.py)은 scripts/ 폴더 안에 있다고 가정해요.
SCRIPT_DIR = Path(__file__).resolve().parent            # scripts/
PROJECT_ROOT = SCRIPT_DIR.parent                         # heritage-rag-agent/
DATA_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"  # 정리된 CSV가 있는 곳


# ------------------------------------------------------------
# 1. 환경변수(.env) 불러오기
# ------------------------------------------------------------
# .env 파일의 위치를 "프로젝트 루트"로 명확히 지정해요.
# 이렇게 하면 터미널에서 어느 폴더에 있는 상태로 실행하든 항상 같은 .env를 찾아요.
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

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

INPUT_CSV = DATA_PROCESSED_DIR / "heritage_gung_detail_clean.csv"

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
# 3. 전체 실행 흐름 (메인 함수)
# ------------------------------------------------------------
def main():
    # ① 정리된 CSV를 읽어와요.
    df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig")

    # moving_urls처럼 빈 칸이 있을 수 있는 컬럼은, 비어 있을 때 NaN 대신 빈 문자열이 되도록 채워줘요.
    # (NaN을 그대로 DB에 넣으려고 하면 오류가 날 수 있어서 미리 방지하는 거예요.)
    df["moving_urls"] = df["moving_urls"].fillna("")
    df["img_url"] = df["img_url"].fillna("")

    print(f"총 {len(df)}건을 임베딩합니다...\n")

    # ② PostgreSQL에 연결해요.
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # ②-1 이미 DB에 저장된 유산은 건너뛰어요. (이어하기 기능)
    #      429로 중간에 멈춰도, 다시 실행하면 저장 안 된 것만 이어서 처리해요.
    #      (테이블에 중복 방지 규칙이 없어서, 이렇게 안 하면 같은 데이터가 두 번 들어가요!)
    cur.execute("SELECT gung_number, serial_number, detail_code FROM heritage_chunks")
    already = set(cur.fetchall())   # 예: {(1, 5, 1), (2, 3, 2), ...}
    df = df[[
        (int(g), int(s), int(d)) not in already
        for g, s, d in zip(df["gung_number"], df["serial_number"], df["detail_code"])
    ]].reset_index(drop=True)
    print(f"이미 저장된 {len(already)}건은 건너뛰고, 남은 {len(df)}건만 처리합니다.\n")

    inserted_count = 0
    failed_batches = []   # 끝까지 실패한 배치를 기록해서, 마지막에 알려줘요.

    # ③ 데이터를 BATCH_SIZE(10)개씩 묶어서 반복해요.
    #    한 건씩 127번 호출하는 대신, 10개씩 묶어서 약 13번만 호출하면
    #    API 호출 횟수를 줄일 수 있어서 무료 한도를 아낄 수 있어요.
    for start in range(0, len(df), BATCH_SIZE):
        batch_df = df.iloc[start:start + BATCH_SIZE]      # 이번에 처리할 10개짜리 조각
        texts = batch_df["document_text"].tolist()          # 그 조각의 본문 글들만 리스트로 꺼내요.

        print(f"[{start + 1} ~ {start + len(batch_df)} / {len(df)}] 임베딩 요청 중...")

        try:
            # ④ 이 배치(묶음)의 글들을 한 번의 호출로 임베딩해요.
            embeddings = embed_with_retry(texts)

            # ⑤ 배치 안의 각 행(row)과 그 행의 임베딩 결과를 짝지어서 하나씩 DB에 저장해요.
            #    zip()은 두 리스트를 1:1로 짝지어주는 함수예요.
            for (_, row), embedding in zip(batch_df.iterrows(), embeddings):
                cur.execute(
                    """
                    INSERT INTO heritage_chunks
                        (gung_number, gung_name, serial_number, detail_code,
                         contents_kor, chunk_text, img_url, moving_urls,
                         embedding_model, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                    """,
                    (
                        int(row["gung_number"]),
                        row["gung_name"],
                        int(row["serial_number"]),
                        int(row["detail_code"]),
                        row["contents_kor"],
                        row["document_text"],
                        row["img_url"],
                        row["moving_urls"],
                        EMBEDDING_MODEL,
                        vector_to_pg_literal(embedding),
                    ),
                )
                inserted_count += 1

            # 이 배치의 작업을 실제 DB에 확정(커밋)해요.
            # 배치 단위로 커밋하면, 중간에 오류가 나도 이전 배치까지는 안전하게 저장돼요.
            conn.commit()

        except Exception as e:
            print(f"    ! 오류 발생: {e}")
            conn.rollback()  # 이 배치에서 오류가 나면, 이 배치의 작업만 취소해서 DB를 깨끗하게 유지해요.
            failed_batches.append(f"{start + 1}~{start + len(batch_df)}")

        # 무료 API 사용 한도(1분 100건)를 지키기 위해 배치 사이에 쉬어요.
        time.sleep(SLEEP_BETWEEN_BATCHES)

    cur.close()
    conn.close()

    print(f"\n이번 실행에서 {inserted_count}건을 heritage_chunks 테이블에 저장했습니다.")
    if failed_batches:
        print(f"실패한 구간: {failed_batches} → 스크립트를 다시 실행하면 이 부분만 이어서 처리해요.")


if __name__ == "__main__":
    main()
