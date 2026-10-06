-- schema.sql
-- ------------------------------------------------------------
-- pgvector 확장 기능을 켜고, 문화유산(궁궐ㆍ종묘ㆍ경희궁ㆍ조선왕릉) 정보를 담을 표를 만드는 스크립트입니다.
--
-- 실행 방법 (터미널에서):
--   psql -h localhost -U postgres -f schema.sql
-- (Docker로 띄웠다면) :
--   docker exec -i postgres psql -U postgres < schema.sql
--
-- 이 파일은 "여러 번 실행해도 안전"해요.
--   - 표가 이미 있으면 새로 만들지 않고 넘어가요 (CREATE TABLE IF NOT EXISTS).
--   - 이미 만들어진 표에 새 컬럼이 필요하면 ALTER TABLE ... ADD COLUMN IF NOT EXISTS 로 추가해요.
--   - 설명(COMMENT)은 다시 실행하면 같은 내용으로 덮어써져요.
-- ------------------------------------------------------------

-- pgvector 기능을 이 데이터베이스에서 쓸 수 있게 켜줍니다. (데이터베이스당 한 번만 실행하면 돼요.)
CREATE EXTENSION IF NOT EXISTS vector;

-- 문화유산 정보와 임베딩 벡터를 함께 저장할 표입니다.
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
    embedding       vector(768),            -- 임베딩 벡터. 768은 Gemini 임베딩 모델의 출력 차원과 같아야 해요.
    ccba_asno       TEXT,                   -- 국가유산 종합 API의 지정번호 (조선왕릉·경희궁지·궁궐 개요용, 13자리 문자열)
    heritage_type   TEXT,                   -- 유산 유형: 건물·시설 / 개요 / 능역
    designation     TEXT,                   -- 지정 종목: 사적 / 국보 / 보물 / 국가무형유산 등
    source          TEXT,                   -- 출처: 데이터를 가져온 기관·API 이름
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 등록시간: 행이 처음 저장된 시각 (자동 기록)
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()   -- 수정시간: 행이 마지막으로 바뀐 시각 (UPDATE 때 자동 갱신)
);

-- 이미 예전 버전의 표가 만들어져 있는 DB를 위해, 새 컬럼을 따로 한 번 더 추가해요.
-- (위 CREATE TABLE은 표가 이미 있으면 통째로 건너뛰기 때문에, 새 컬럼은 이 줄이 있어야 기존 표에 들어가요.)
ALTER TABLE heritage_chunks ADD COLUMN IF NOT EXISTS ccba_asno TEXT;
ALTER TABLE heritage_chunks ADD COLUMN IF NOT EXISTS heritage_type TEXT;
ALTER TABLE heritage_chunks ADD COLUMN IF NOT EXISTS designation TEXT;
ALTER TABLE heritage_chunks ADD COLUMN IF NOT EXISTS source TEXT;
-- 등록/수정시간도 같은 방식으로 추가해요. (※ 이미 들어 있던 행은 "이 줄을 실행한 시각"으로 채워져요. 실제 최초 저장 시각은 알 수 없어요.)
ALTER TABLE heritage_chunks ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE heritage_chunks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- 같은 지정번호가 두 번 저장되지 않게 막아요. (중복 저장 방지 + "이미 저장했는지" 빠르게 확인)
-- 기존 궁궐 127건은 ccba_asno가 비어(NULL) 있는데, PostgreSQL은 NULL끼리는 중복으로 보지 않아서 문제없어요.
CREATE UNIQUE INDEX IF NOT EXISTS ux_heritage_chunks_ccba_asno ON heritage_chunks (ccba_asno);


-- 이미 저장돼 있던 행에 새 컬럼 값 채우기 (source가 비어 있는 행에만 실행되므로 다시 실행해도 안전해요)
--   ※ UPDATE이므로, 아래 트리거가 이미 만들어져 있는 DB에서는 이때 한 번 해당 행들의 수정시간(updated_at)도 현재 시각으로 바뀌어요.
UPDATE heritage_chunks
   SET source = '국가유산청 궁궐·종묘 Open API', heritage_type = '건물·시설'
 WHERE ccba_asno IS NULL AND source IS NULL;                 -- 기존 궁궐·종묘 127건

UPDATE heritage_chunks
   SET source = '국가유산청 국가유산 종합 Open API', designation = '사적',
       heritage_type = CASE WHEN gung_name = '조선왕릉' THEN '능역' ELSE '개요' END
 WHERE ccba_asno IS NOT NULL AND source IS NULL;             -- 조선왕릉 18건 + 경희궁지

-- 수정시간 자동 갱신 장치(트리거)
--   created_at은 DEFAULT now()만으로 충분하지만, updated_at은 "수정할 때마다" 바꿔 줘야 해요.
--   파이썬 코드에서 매번 updated_at을 적지 않아도 되도록, DB가 UPDATE 직전에 알아서 현재 시각을 넣어 줘요.
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();   -- 바뀌는 새 행(NEW)의 수정시간을 지금으로 설정
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_heritage_chunks_updated_at ON heritage_chunks;   -- 다시 실행해도 안전하도록 먼저 지움
CREATE TRIGGER trg_heritage_chunks_updated_at
    BEFORE UPDATE ON heritage_chunks
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ------------------------------------------------------------
-- 표/컬럼 설명 (논리명 + 설명)
--   "논리명"은 사람이 읽는 한글 이름, "컬럼명"은 DB에 실제로 쓰는 영어 이름이에요.
--   형식: '논리명: 설명'   ※ 작은따옴표(')는 문장 안에 쓰지 않았어요 (SQL이 깨질 수 있어서).
--   확인 방법:  docker exec -it postgres psql -U postgres -c "\d+ heritage_chunks"   (맨 오른쪽 Description 칸)
-- ------------------------------------------------------------
COMMENT ON TABLE heritage_chunks IS
    '문화유산 청크: 유산 1건의 설명글(chunk_text)과 임베딩 벡터를 저장하는 RAG 검색용 표. 궁궐 5곳(127건)과 조선왕릉·경희궁지가 함께 들어감';

COMMENT ON COLUMN heritage_chunks.id IS
    '청크 번호: 행마다 자동으로 붙는 고유 번호 (기본키)';
COMMENT ON COLUMN heritage_chunks.gung_number IS
    '궁 번호: 궁궐 API의 궁 번호 (1=경복궁 2=창덕궁 3=창경궁 4=덕수궁 5=종묘). 조선왕릉·경희궁지는 해당 없음이라 NULL';
COMMENT ON COLUMN heritage_chunks.gung_name IS
    '분류명(궁 이름): 검색 결과와 출처에 표시되는 소속 이름. 예: 경복궁, 종묘, 경희궁, 조선왕릉. 이름은 궁이지만 왕릉도 여기에 분류명으로 넣음';
COMMENT ON COLUMN heritage_chunks.serial_number IS
    '원본 순번: 궁궐 API가 유산마다 붙인 순번(키값). 궁 번호·세부코드와 함께 궁궐 유산을 구분하는 값. 조선왕릉·경희궁지는 NULL';
COMMENT ON COLUMN heritage_chunks.detail_code IS
    '원본 세부코드: 궁궐 API의 세부코드. 같은 순번 안에서 세부 항목을 구분함. 조선왕릉·경희궁지는 NULL';
COMMENT ON COLUMN heritage_chunks.contents_kor IS
    '국가유산명: 유산의 한글 이름. 예: 광화문, 영월 장릉, 경희궁지';
COMMENT ON COLUMN heritage_chunks.chunk_text IS
    '임베딩 본문: 벡터로 바꾼 실제 글이자 LLM에게 참고 자료로 넘기는 글. 형식은 [분류명] 유산명 - 설명글';
COMMENT ON COLUMN heritage_chunks.img_url IS
    '대표 이미지 주소: 화면의 출처 카드에 보여줄 이미지 경로. 없으면 빈 값';
COMMENT ON COLUMN heritage_chunks.moving_urls IS
    '동영상 주소 목록: 동영상이 여러 개면 세미콜론( ; )으로 이어 붙여 저장. 궁궐 API에만 있고 조선왕릉·경희궁지는 빈 값';
COMMENT ON COLUMN heritage_chunks.embedding_model IS
    '임베딩 모델명: 이 벡터를 만든 모델 이름 (예: gemini-embedding-001). 모델을 바꾸면 벡터를 다시 만들어야 하므로 기록해 둠';
COMMENT ON COLUMN heritage_chunks.embedding IS
    '임베딩 벡터: 본문 의미를 768개 숫자로 바꾼 값. 질문 벡터와 코사인 거리(<=>)로 비교해 비슷한 유산을 찾음';
COMMENT ON COLUMN heritage_chunks.ccba_asno IS
    '국가유산 지정번호: 국가유산청 종합 API의 지정번호 (예: 0002710000000). 13자리 문자열이며 앞자리 0을 지키려고 숫자가 아닌 TEXT로 저장. 조선왕릉·경희궁지의 고유 키이며 기존 궁궐 127건은 NULL';
COMMENT ON COLUMN heritage_chunks.heritage_type IS
    '유산 유형: 이 행이 무엇을 설명하는지 구분. 건물·시설(궁궐 안 건물 해설) / 개요(궁궐·궁궐터 전체 설명) / 능역(조선왕릉 능역 설명). 같은 궁 안에서 건물과 개요를 구분할 때 씀';
COMMENT ON COLUMN heritage_chunks.designation IS
    '지정 종목: 국가유산 지정 종류 (사적, 국보, 보물, 국가무형유산 등). 국가유산 종합 API 데이터에만 있고 궁궐·종묘 API 데이터는 NULL';
COMMENT ON COLUMN heritage_chunks.source IS
    '출처: 데이터를 가져온 기관과 API 이름 (예: 국가유산청 궁궐·종묘 Open API). 공공데이터 이용 조건인 출처 표시에 사용';
COMMENT ON COLUMN heritage_chunks.created_at IS
    '등록시간: 이 행이 처음 저장된 시각 (자동 기록, 시간대 포함). 2026-10 컬럼 추가 전에 있던 궁궐 127건은 컬럼을 추가한 시각이 들어 있어 실제 최초 저장 시각과 다름';
COMMENT ON COLUMN heritage_chunks.updated_at IS
    '수정시간: 이 행이 마지막으로 바뀐 시각 (UPDATE 할 때 트리거가 자동 갱신). 설명글을 다시 수집해 임베딩을 새로 만든 시점을 알 수 있음';
