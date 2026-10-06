-- schema.sql  (v2: 표 분리 버전)
-- ------------------------------------------------------------
-- 문화유산 RAG용 표를 만드는 스크립트입니다. (pgvector 사용)
--
-- v1에서는 heritage_chunks 표 하나에 유산 정보, 설명글, 벡터, 이미지, 출처를 모두 넣었어요.
-- v2에서는 "무엇이 하나의 유산인가"와 "그 유산의 청크"를 나눠서 아래 표로 저장해요.
--
--   source          출처(기관·API)와 이용 조건
--   heritage        유산 1건 (키: 종목 코드 + 지정번호, 또는 궁 번호 + 순번 + 세부코드)
--                   영어·일본어·중국어 이름도 name_en / name_ja / name_zh 컬럼에 같이 저장
--   heritage_chunk  유산의 설명글(청크) + 임베딩 벡터 (검색 대상)
--   media           이미지·동영상 주소
--   raw_document    수집한 원본 파일 기록 (재수집 비교용)
--   ingest_run      수집·임베딩 실행 기록
--
-- 실행 방법 (Docker로 띄운 경우, backend/db 폴더에서):
--   docker exec -i postgres psql -U postgres < schema.sql
--
-- 이미 v1(heritage_chunks 표)을 쓰고 있다면, 이 파일을 실행한 "다음에" migrate_v1_to_v2.sql도 실행하세요.
-- 이미 heritage_alias 표가 있는 DB라면(별칭 표를 합치기 전 DB), 이 파일을 실행한 "다음에"
-- migrate_alias_to_heritage.sql도 실행하세요. (heritage_alias의 이름들을 heritage 컬럼으로 옮겨 줘요)
--
-- 이 파일은 "여러 번 실행해도 안전"해요. (CREATE ... IF NOT EXISTS, ON CONFLICT DO NOTHING)
-- ------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS vector;

-- 수정시간 자동 갱신 장치(트리거 함수)
--   UPDATE 할 때마다 DB가 알아서 updated_at을 현재 시각으로 바꿔 줘요. (파이썬에서 매번 적지 않아도 돼요)
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- ------------------------------------------------------------
-- 1. source : 출처
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS source (
    id          SMALLSERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,      -- 출처 이름 (화면의 출처 표시에 사용)
    license     TEXT,                      -- 이용 조건
    url         TEXT,                      -- 출처 사이트/API 주소
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO source (name, license, url) VALUES
    ('국가유산청 궁궐·종묘 Open API',
     '공공저작물: 출처 표시 시 자유 이용 (국가유산포털 안내 기준)',
     'https://www.heritage.go.kr/heri/gungDetail/gogungListOpenApi.do'),
    ('국가유산청 국가유산 종합 Open API',
     '미확인: 이용 조건을 아직 확인하지 못함 (출처는 표시할 것)',
     'https://www.khs.go.kr/cha/SearchKindOpenapiList.do')
ON CONFLICT (name) DO NOTHING;


-- ------------------------------------------------------------
-- 2. heritage : 유산 1건
--    유산을 구분하는 키는 두 가지예요. (둘 중 하나는 반드시 채워야 해요)
--      A) 국가유산 종합 API 데이터: (ccba_kdcd 종목 코드, ccba_asno 지정번호)
--         ※ 지정번호만으로는 유일하지 않아요. 종목이 다르면 같은 번호가 있어요. (예: 국보 숭례문과 무형유산 종묘제례악)
--      B) 궁궐·종묘 API 데이터: (gung_number 궁 번호, serial_number 순번, detail_code 세부코드)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS heritage (
    id            BIGSERIAL PRIMARY KEY,
    ccba_kdcd     TEXT,                    -- 종목 코드 (11 국보, 12 보물, 13 사적, 16 천연기념물, 17 국가무형유산, 79 국가등록유산)
    ccba_asno     TEXT,                    -- 지정번호 13자리 문자열 (앞자리 0 보존)
    ccba_ctcd     TEXT,                    -- 시도 코드 (상세 조회 API에 필요한 값. 이전 데이터는 비어 있을 수 있음)
    gung_number   INT,                     -- 궁 번호 (1~5), 궁궐 API 데이터만
    serial_number INT,                     -- 궁궐 API 순번
    detail_code   INT,                     -- 궁궐 API 세부코드
    group_name    TEXT NOT NULL,           -- 분류명: 경복궁, 종묘, 경희궁, 조선왕릉 등 (화면 출처에 표시)
    name_kor      TEXT NOT NULL,           -- 유산명 (개요 행은 "개요"로 저장해 출처가 [창덕궁 개요]로 보이게 함)
    name_en       TEXT,                    -- 영어 이름 (궁궐·종묘 API 데이터만 있고, 없으면 NULL)
    name_ja       TEXT,                    -- 일본어 이름
    name_zh       TEXT,                    -- 중국어 이름 (일부 유산은 없음)
    entity_type   TEXT NOT NULL,           -- 건물·시설 / 개요 / 능역
    designation   TEXT,                    -- 지정 종목 이름 (사적, 국보 ...)
    parent_id     BIGINT REFERENCES heritage (id) ON DELETE SET NULL,  -- 상위 유산 (건물 -> 소속 궁 개요)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_heritage_has_key CHECK (
        (ccba_kdcd IS NOT NULL AND ccba_asno IS NOT NULL)
        OR (gung_number IS NOT NULL AND serial_number IS NOT NULL AND detail_code IS NOT NULL)
    )
);

-- 이미 heritage 표가 있는 DB에서도 이 파일을 다시 실행하면 새 컬럼이 추가되도록 한 번 더 적어 둬요.
ALTER TABLE heritage ADD COLUMN IF NOT EXISTS name_en TEXT;
ALTER TABLE heritage ADD COLUMN IF NOT EXISTS name_ja TEXT;
ALTER TABLE heritage ADD COLUMN IF NOT EXISTS name_zh TEXT;

-- 같은 유산이 두 번 들어가지 않게 막아요. (NULL이 있는 행은 해당 키의 검사에서 빠져요)
CREATE UNIQUE INDEX IF NOT EXISTS ux_heritage_kdcd_asno
    ON heritage (ccba_kdcd, ccba_asno) WHERE ccba_asno IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_heritage_gung_key
    ON heritage (gung_number, serial_number, detail_code) WHERE gung_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_heritage_parent ON heritage (parent_id);
CREATE INDEX IF NOT EXISTS ix_heritage_group_name ON heritage (group_name, name_kor);

DROP TRIGGER IF EXISTS trg_heritage_updated_at ON heritage;
CREATE TRIGGER trg_heritage_updated_at
    BEFORE UPDATE ON heritage FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ------------------------------------------------------------
-- 3. heritage_chunk : 설명글 + 임베딩 (RAG 검색 대상)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS heritage_chunk (
    id              BIGSERIAL PRIMARY KEY,
    heritage_id     BIGINT NOT NULL REFERENCES heritage (id) ON DELETE CASCADE,
    source_id       SMALLINT NOT NULL REFERENCES source (id),
    chunk_type      TEXT NOT NULL,         -- 개요 / 건물 해설 / 지정 설명
    chunk_no        INT NOT NULL DEFAULT 1,-- 같은 종류의 글을 여러 청크로 나눌 때의 순서
    chunk_text      TEXT NOT NULL,         -- 임베딩한 본문(설명글 원문, 머리말 없음). 머리말 [분류명] 유산명은 heritage 컬럼에서 LLM에게 줄 때 붙여요
    content_hash    TEXT NOT NULL,         -- 본문의 md5 값 (바뀐 글만 다시 임베딩하려고 기록)
    embedding_model TEXT NOT NULL,         -- 벡터를 만든 모델 이름
    embedding       vector(768),           -- 임베딩 벡터 (Gemini 출력 차원과 같아야 함)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (heritage_id, chunk_type, chunk_no)
);
CREATE INDEX IF NOT EXISTS ix_heritage_chunk_source ON heritage_chunk (source_id);

DROP TRIGGER IF EXISTS trg_heritage_chunk_updated_at ON heritage_chunk;
CREATE TRIGGER trg_heritage_chunk_updated_at
    BEFORE UPDATE ON heritage_chunk FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ------------------------------------------------------------
-- 4. (삭제) heritage_alias
--    영어·일본어·중국어 이름은 heritage 표의 name_en / name_ja / name_zh 컬럼으로 합쳤어요.
--    (유산 1건에 언어별 이름이 하나씩뿐이라 따로 표를 둘 필요가 없었어요.)
--    별칭이 여러 개인 경우(예: 인물의 다른 이름)는 3단계의 entity_alias 표에서 다뤄요.
-- ------------------------------------------------------------


-- ------------------------------------------------------------
-- 5. media : 이미지·동영상
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS media (
    id           BIGSERIAL PRIMARY KEY,
    heritage_id  BIGINT NOT NULL REFERENCES heritage (id) ON DELETE CASCADE,
    media_type   TEXT NOT NULL CHECK (media_type IN ('image', 'video')),
    url          TEXT NOT NULL,
    sort_order   INT NOT NULL DEFAULT 0,   -- 같은 유산 안에서의 순서 (0이 대표)
    license      TEXT,                     -- 이미지 이용 조건 (4단계 전에 확인 필요, 지금은 비워 둠)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (heritage_id, url)
);


-- ------------------------------------------------------------
-- 6. raw_document : 수집 원본 기록 (원본 파일은 디스크에 보관, 여기엔 위치와 해시만)
--    ※ 아직 수집 스크립트가 채우지 않아요. 수집기를 하나로 합칠 때 연결할 예정이에요.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_document (
    id            BIGSERIAL PRIMARY KEY,
    source_id     SMALLINT NOT NULL REFERENCES source (id),
    external_key  TEXT NOT NULL,           -- 출처에서의 키 (예: 종목코드:지정번호)
    payload_path  TEXT,                    -- 원본 XML 파일 위치
    content_hash  TEXT,                    -- 원본의 해시 (바뀌었는지 비교)
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_id, external_key)
);


-- ------------------------------------------------------------
-- 7. ingest_run : 임베딩/저장 실행 기록
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingest_run (
    id              BIGSERIAL PRIMARY KEY,
    scope           TEXT NOT NULL,         -- 어떤 입력을 처리했는지 (all / gung / royal)
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    inserted        INT NOT NULL DEFAULT 0,
    updated         INT NOT NULL DEFAULT 0,
    skipped         INT NOT NULL DEFAULT 0,
    failed_batches  INT NOT NULL DEFAULT 0,
    note            TEXT
);


-- ------------------------------------------------------------
-- 8. (삭제) 호환용 뷰 heritage_chunks
--    검색 코드(rag.py, search_test.py, eval_search.py)가 v2 표(heritage_chunk + heritage)를 직접 읽도록 바뀌어서
--    옛 호환 뷰는 더 이상 필요 없어요. 아래는 "남아 있는 뷰만" 정리하는 안전한 코드예요.
--    (v1 "표" heritage_chunks가 남아 있으면 건드리지 않아요. 여러 번 실행해도 안전해요.)
-- ------------------------------------------------------------
DO $$
BEGIN
    IF (SELECT relkind FROM pg_class WHERE oid = to_regclass('heritage_chunks')) = 'v' THEN
        DROP VIEW heritage_chunks;
    END IF;
END $$;
DROP FUNCTION IF EXISTS create_heritage_chunks_view();


-- ------------------------------------------------------------
-- 표/컬럼 설명 (논리명: 설명)
--   확인: docker exec -it postgres psql -U postgres -c "\d+ heritage"
-- ------------------------------------------------------------
COMMENT ON TABLE source IS '출처: 데이터를 가져온 기관·API와 이용 조건';
COMMENT ON COLUMN source.id IS '출처 번호: 자동 부여되는 고유 번호 (기본키)';
COMMENT ON COLUMN source.name IS '출처명: 화면의 출처 표시에 쓰는 이름. 중복 불가';
COMMENT ON COLUMN source.license IS '이용 조건: 공공데이터 이용 조건. 확인하지 못했으면 미확인이라고 적음';
COMMENT ON COLUMN source.url IS '출처 주소: API 또는 사이트 주소';
COMMENT ON COLUMN source.created_at IS '등록시간: 이 행이 처음 저장된 시각';

COMMENT ON TABLE heritage IS '유산: 유산 1건당 1행. 설명글은 heritage_chunk, 이미지는 media에 나뉘어 저장됨. 영어·일본어·중국어 이름은 name_en/name_ja/name_zh 컬럼에 같이 저장';
COMMENT ON COLUMN heritage.id IS '유산 번호: 자동 부여되는 고유 번호 (기본키)';
COMMENT ON COLUMN heritage.ccba_kdcd IS '종목 코드: 국가유산 종합 API의 종목 코드 (11 국보, 12 보물, 13 사적, 16 천연기념물, 17 국가무형유산, 79 국가등록유산). 지정번호와 함께 유산을 구분함. 궁궐 API 데이터는 NULL';
COMMENT ON COLUMN heritage.ccba_asno IS '지정번호: 13자리 문자열 (앞자리 0 보존). 종목이 다르면 같은 번호가 있어 종목 코드와 함께 써야 유일함. 궁궐 API 데이터는 NULL';
COMMENT ON COLUMN heritage.ccba_ctcd IS '시도 코드: 종합 API 상세 조회에 필요한 값. v1에서 옮긴 행은 비어 있다가 다음 임베딩 실행 때 채워질 수 있음';
COMMENT ON COLUMN heritage.gung_number IS '궁 번호: 궁궐 API의 궁 번호 (1 경복궁, 2 창덕궁, 3 창경궁, 4 덕수궁, 5 종묘). 종합 API 데이터는 NULL';
COMMENT ON COLUMN heritage.serial_number IS '원본 순번: 궁궐 API가 붙인 순번. 궁 번호·세부코드와 함께 궁궐 유산을 구분함';
COMMENT ON COLUMN heritage.detail_code IS '원본 세부코드: 궁궐 API의 세부코드';
COMMENT ON COLUMN heritage.name_en IS '영어 이름: 궁궐·종묘 API 데이터만 값이 있음. 없으면 NULL';
COMMENT ON COLUMN heritage.name_ja IS '일본어 이름: 궁궐·종묘 API 데이터만 값이 있음. 없으면 NULL';
COMMENT ON COLUMN heritage.name_zh IS '중국어 이름: 궁궐·종묘 API 데이터 중 일부만 값이 있음. 없으면 NULL';
COMMENT ON COLUMN heritage.group_name IS '분류명: 화면 출처에 표시되는 소속 이름 (경복궁, 종묘, 경희궁, 조선왕릉 등)';
COMMENT ON COLUMN heritage.name_kor IS '유산명: 한글 이름. 궁궐 전체 설명 행은 개요로 저장해 출처가 [창덕궁 개요]처럼 보이게 함';
COMMENT ON COLUMN heritage.entity_type IS '유산 유형: 건물·시설 / 개요 / 능역';
COMMENT ON COLUMN heritage.designation IS '지정 종목: 사적, 국보, 보물 등 종목 이름';
COMMENT ON COLUMN heritage.parent_id IS '상위 유산: 건물이면 소속 궁의 개요 행 번호. 최상위는 NULL';
COMMENT ON COLUMN heritage.created_at IS '등록시간: 이 행이 처음 저장된 시각 (v1에서 옮긴 행은 v1의 값을 그대로 가져옴)';
COMMENT ON COLUMN heritage.updated_at IS '수정시간: 마지막으로 바뀐 시각 (트리거가 자동 갱신)';

COMMENT ON TABLE heritage_chunk IS '유산 청크: 검색 대상이 되는 설명글과 임베딩 벡터. 유산 1건에 여러 청크가 생길 수 있음';
COMMENT ON COLUMN heritage_chunk.id IS '청크 번호: 자동 부여되는 고유 번호 (기본키)';
COMMENT ON COLUMN heritage_chunk.heritage_id IS '유산 번호: 이 글이 설명하는 유산 (heritage.id). 유산을 지우면 같이 지워짐';
COMMENT ON COLUMN heritage_chunk.source_id IS '출처 번호: 이 글을 가져온 출처 (source.id)';
COMMENT ON COLUMN heritage_chunk.chunk_type IS '글 종류: 개요 / 건물 해설 / 지정 설명';
COMMENT ON COLUMN heritage_chunk.chunk_no IS '청크 순서: 같은 종류의 긴 글을 나눌 때의 순서. 지금은 모두 1';
COMMENT ON COLUMN heritage_chunk.chunk_text IS '임베딩 본문: 벡터로 바꾼 설명글 원문(머리말 없음). LLM에게 줄 때는 heritage.group_name·name_kor로 [분류] 유산명 - 머리말을 붙여서 넘긴다';
COMMENT ON COLUMN heritage_chunk.content_hash IS '본문 해시: chunk_text의 md5. 글이 바뀌었는지 빠르게 비교하는 데 씀';
COMMENT ON COLUMN heritage_chunk.embedding_model IS '임베딩 모델명: 벡터를 만든 모델. 모델을 바꾸면 다시 만들어야 해서 기록함';
COMMENT ON COLUMN heritage_chunk.embedding IS '임베딩 벡터: 본문 의미를 768개 숫자로 바꾼 값. 질문 벡터와 코사인 거리(<=>)로 비교함';
COMMENT ON COLUMN heritage_chunk.created_at IS '등록시간: 이 행이 처음 저장된 시각';
COMMENT ON COLUMN heritage_chunk.updated_at IS '수정시간: 마지막으로 바뀐 시각 (글을 다시 임베딩한 시점)';

COMMENT ON TABLE media IS '미디어: 유산의 이미지·동영상 주소';
COMMENT ON COLUMN media.id IS '미디어 번호: 자동 부여되는 고유 번호 (기본키)';
COMMENT ON COLUMN media.heritage_id IS '유산 번호: 이 미디어의 주인 유산 (heritage.id)';
COMMENT ON COLUMN media.media_type IS '종류: image 또는 video';
COMMENT ON COLUMN media.url IS '주소: 이미지·동영상 경로';
COMMENT ON COLUMN media.sort_order IS '순서: 같은 유산 안에서의 순서. 0이 대표';
COMMENT ON COLUMN media.license IS '이용 조건: 이미지 이용 조건. 멀티모달 단계 전에 확인 필요하며 지금은 비어 있음';
COMMENT ON COLUMN media.created_at IS '등록시간: 이 행이 처음 저장된 시각';

COMMENT ON TABLE raw_document IS '수집 원본 기록: 원본 XML의 위치와 해시. 재수집 때 바뀐 것만 찾는 용도. 아직 채워지지 않음';
COMMENT ON COLUMN raw_document.id IS '원본 번호: 자동 부여되는 고유 번호 (기본키)';
COMMENT ON COLUMN raw_document.source_id IS '출처 번호: source.id';
COMMENT ON COLUMN raw_document.external_key IS '출처 키: 출처에서 쓰는 유산 키 (예: 종목코드:지정번호)';
COMMENT ON COLUMN raw_document.payload_path IS '원본 위치: 디스크에 보관한 원본 파일 경로';
COMMENT ON COLUMN raw_document.content_hash IS '원본 해시: 원본이 바뀌었는지 비교하는 값';
COMMENT ON COLUMN raw_document.fetched_at IS '수집시간: 원본을 가져온 시각';

COMMENT ON TABLE ingest_run IS '실행 기록: embed_and_store.py를 한 번 실행할 때마다 1행';
COMMENT ON COLUMN ingest_run.id IS '실행 번호: 자동 부여되는 고유 번호 (기본키)';
COMMENT ON COLUMN ingest_run.scope IS '처리 범위: all / gung / royal';
COMMENT ON COLUMN ingest_run.started_at IS '시작시간';
COMMENT ON COLUMN ingest_run.finished_at IS '종료시간: 끝까지 안 끝났으면 NULL';
COMMENT ON COLUMN ingest_run.inserted IS '새로 저장한 건수';
COMMENT ON COLUMN ingest_run.updated IS '내용이 바뀌어 갱신한 건수';
COMMENT ON COLUMN ingest_run.skipped IS '이미 저장돼 건너뛴 건수';
COMMENT ON COLUMN ingest_run.failed_batches IS '끝까지 실패한 배치 수';
COMMENT ON COLUMN ingest_run.note IS '메모';
