-- schema.sql
-- ------------------------------------------------------------
-- pgvector 확장 기능을 켜고, 궁궐ㆍ종묘 유산 정보를 담을 표를 만드는 스크립트입니다.
--
-- 실행 방법 (터미널에서):
--   psql -h localhost -U postgres -f schema.sql
-- (Docker로 띄웠다면) :
--   docker exec -i postgres psql -U postgres < schema.sql
-- ------------------------------------------------------------

-- pgvector 기능을 이 데이터베이스에서 쓸 수 있게 켜줍니다. (데이터베이스당 한 번만 실행하면 돼요.)
CREATE EXTENSION IF NOT EXISTS vector;

-- 궁궐ㆍ종묘 유산 정보와 임베딩 벡터를 함께 저장할 표입니다.
CREATE TABLE IF NOT EXISTS heritage_chunks (
    id              BIGSERIAL PRIMARY KEY,  -- 자동으로 늘어나는 고유 번호
    gung_number     INT,                    -- 궁 번호 (1~5)
    gung_name       TEXT,                   -- 궁 이름 (예: 창경궁)
    serial_number   INT,                    -- API 원본의 순번(키값)
    detail_code     INT,                    -- API 원본의 세부코드
    contents_kor    TEXT,                   -- 국가유산명 (예: 홍화문)
    chunk_text      TEXT NOT NULL,          -- 임베딩한 실제 본문 (document_text)
    img_url         TEXT,                   -- 대표 이미지 경로
    moving_urls     TEXT,                   -- 동영상 경로 (여러 개면 세미콜론으로 구분됨)
    embedding_model TEXT NOT NULL,          -- 어떤 모델로 이 벡터를 만들었는지 기록 (모델 교체 대비)
    embedding       vector(768)             -- 임베딩 벡터. 768은 Gemini 임베딩 모델의 출력 차원과 같아야 해요.
);
