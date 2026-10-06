# DB 3층 구조 설계안 (heritage-rag-agent)

> 상태: **설계안(미적용)**. 아래 SQL은 실제 DB에서 실행해 보지 못했습니다. 적용 전에 반드시 테스트 DB에서 먼저 돌려 보세요.
> 기준 파일: `backend/db/schema.sql` (v2). 확인한 현재 상태를 먼저 정리하고, 거기에 **더하는 방식**으로 설계했습니다.
>
> **2026-10-04 갱신 — 한꺼번에 만들지 말고 단계적으로 적용하세요.**
> - 지금(실록을 RAG에 넣을 때): `source.code` 컬럼 + `sillok_article` 표 + `heritage_chunk.article_id`만.
> - 기상 XLS 확인 후: `weather_record`.
> - 3단계(관계 그래프): `entity`, `entity_alias`, `relation`. 그 전에는 비워 둘 표라 미리 만들 필요가 없습니다.
> - `heritage_alias` 표는 이미 `heritage`의 `name_en / name_ja / name_zh` 컬럼으로 합쳤습니다(아래 0번 표의 해당 줄은 합치기 전 기준).
> - 실제 DB는 6개 표 + 호환 뷰 구조이고, 컬럼과 실제 값은 Notion "DB 스키마" 페이지에 있습니다.

---

## 0. 먼저 바로잡을 점

`heritage_chunks`는 이미 표가 아니라 **호환용 읽기 전용 뷰**입니다. 실제 표는 v2에서 이미 나뉘어 있어요.

| 현재 v2 표 | 하는 일 | 3층 구조에서의 위치 |
|---|---|---|
| `source` | 출처 이름·이용 조건·URL | ① 출처 등록표 (코드 컬럼만 없음) |
| `raw_document` | 원본 파일 위치와 해시 (아직 안 채워짐) | ② 원본 기록 |
| `heritage` | 유산 1건 | ② 출처별 표 (국가유산청 계열) |
| `heritage_chunk` | 설명글 + 임베딩 | 검색 대상 (RAG) |
| `heritage_alias`, `media` | 별칭, 이미지 | 유산 부속 표 |
| `ingest_run` | 임베딩 실행 기록 | 운영 기록 |
| (없음) | 실록 기사, 기상 기록 | ② 에 추가 |
| (없음) | 인물·사건·지역 노드, 관계 | ③ 에 추가 |

즉 **새로 갈아엎는 게 아니라 3가지를 추가**하는 설계입니다.

---

## 1. 전체 그림

```
① 출처 등록표        source (+ code 컬럼 추가)
        │
② 출처별 표          heritage / heritage_chunk (기존, 국가유산청)
                     sillok_article          (신규, 실록 기사)
                     weather_record          (신규, 기상 기록 — 파일 확인 후 컬럼 확정)
        │
③ 통합 그래프 표     entity (노드: 인물·사건·지역·유산)
                     entity_alias (노드의 다른 이름)
                     relation (A –관계→ B + 근거)
```

원칙
- 원본 모양은 ②에 그대로, 그래프용 통합은 ③에서만 합니다.
- 모든 행은 `source_id`(→ source.code)를 가지고, 출처 안의 원래 번호(`source_key`)를 함께 보관합니다.
- 관계(`relation`)에는 근거(어느 기사의 어느 문장인지)를 반드시 남깁니다.

---

## 2. 출처코드

| code | 출처 | 비고 |
|---|---|---|
| `GUNG` | 국가유산청 궁궐·종묘 Open API | 기존 source 1번 |
| `HERITAGE_API` | 국가유산청 국가유산 종합 Open API (왕릉, 나중에 국보·보물) | 기존 source 2번. 이용 조건 미확인 |
| `SILLOK` | 조선왕조실록 원문 XML (공공누리 1유형) | 신규 |
| `WEATHER` | 기상청 조선왕조실록 기상기록 (공공누리 1유형, 12,184행) | 신규. 파일은 아직 미확인 |
| `PERSON_API` | 인물 데이터 API | **어떤 API인지 미정** |

---

## 3. 변경 SQL 초안 (additive, 여러 번 실행해도 안전하게)

```sql
-- ① source 에 코드 컬럼 추가 ------------------------------------------
ALTER TABLE source ADD COLUMN IF NOT EXISTS code         TEXT;       -- 'SILLOK' 같은 짧은 출처코드
ALTER TABLE source ADD COLUMN IF NOT EXISTS provider     TEXT;       -- 제공기관
ALTER TABLE source ADD COLUMN IF NOT EXISTS collected_at DATE;       -- 수집일
CREATE UNIQUE INDEX IF NOT EXISTS ux_source_code ON source (code) WHERE code IS NOT NULL;

UPDATE source SET code = 'GUNG'         WHERE name = '국가유산청 궁궐·종묘 Open API'       AND code IS NULL;
UPDATE source SET code = 'HERITAGE_API' WHERE name = '국가유산청 국가유산 종합 Open API'   AND code IS NULL;

INSERT INTO source (name, code, provider, license, url) VALUES
  ('조선왕조실록 원문 XML', 'SILLOK', '국사편찬위원회', '공공누리 1유형: 출처 표시', 'https://sillok.history.go.kr'),
  ('기상청 조선왕조실록 기상기록', 'WEATHER', '기상청 국가기후데이터센터', '공공누리 1유형: 출처 표시', 'https://www.data.go.kr/data/15050689/fileData.do')
ON CONFLICT (name) DO NOTHING;


-- ② 실록 기사 (출처별 표) ---------------------------------------------
-- clean_sillok.py 의 결과 CSV(sillok_heritage_articles_clean.csv)를 그대로 옮기는 표
CREATE TABLE IF NOT EXISTS sillok_article (
    article_id        TEXT PRIMARY KEY,                       -- 예: wda_11108022_002 (실록 기사 번호)
    source_id         SMALLINT NOT NULL REFERENCES source (id),
    reign_title       TEXT,                                   -- 세종실록 등
    regnal_year       INT,                                    -- 재위 몇 년
    month             INT,
    leap_month        BOOLEAN,
    day               INT,
    date_label        TEXT,                                   -- 표시용 날짜
    title             TEXT NOT NULL,                          -- 한글 기사 제목
    text_hanja        TEXT NOT NULL,                          -- 한문 원문 (절대 수정하지 않음)
    summary_kor       TEXT,                                   -- 검색용 한글 요약 (나중에 LLM으로 생성, 비어 있을 수 있음)
    text_length       INT,
    match_groups      TEXT,                                   -- palace / shrine / tomb
    matched_keywords  TEXT,
    tomb_detail       TEXT,                                   -- 예: 영릉(세종)
    possible_china_tomb BOOLEAN DEFAULT false,
    needs_split       BOOLEAN DEFAULT false,
    source_url        TEXT,                                   -- 형식 미검증
    content_hash      TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_sillok_article_reign ON sillok_article (reign_title, regnal_year);


-- ② 기상 기록: 파일(XLS)을 열어 컬럼을 확인한 뒤 확정 (지금은 자리만) --------
-- CREATE TABLE weather_record (...);


-- 검색 대상(chunk)이 실록 기사도 가리킬 수 있게 확장 --------------------------
ALTER TABLE heritage_chunk ALTER COLUMN heritage_id DROP NOT NULL;
ALTER TABLE heritage_chunk ADD COLUMN IF NOT EXISTS article_id TEXT REFERENCES sillok_article (article_id) ON DELETE CASCADE;
ALTER TABLE heritage_chunk DROP CONSTRAINT IF EXISTS ck_chunk_has_subject;
ALTER TABLE heritage_chunk ADD CONSTRAINT ck_chunk_has_subject
    CHECK (heritage_id IS NOT NULL OR article_id IS NOT NULL);       -- 유산 또는 기사 중 하나는 반드시 있어야 함
CREATE UNIQUE INDEX IF NOT EXISTS ux_chunk_article
    ON heritage_chunk (article_id, chunk_type, chunk_no) WHERE article_id IS NOT NULL;


-- ③ 통합 그래프 표 ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS entity (
    id           BIGSERIAL PRIMARY KEY,
    entity_type  TEXT NOT NULL CHECK (entity_type IN ('person','event','place','heritage')),
    name         TEXT NOT NULL,
    source_id    SMALLINT NOT NULL REFERENCES source (id),
    source_key   TEXT NOT NULL,                                   -- 출처 안의 원래 번호 (예: M_0033967)
    heritage_id  BIGINT REFERENCES heritage (id) ON DELETE SET NULL,  -- type='heritage' 일 때 기존 heritage 와 연결
    extra        JSONB,                                           -- 생몰년 등 출처별 부가 정보
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_id, source_key)                                -- 같은 출처의 같은 번호는 한 번만
);

CREATE TABLE IF NOT EXISTS entity_alias (
    id         BIGSERIAL PRIMARY KEY,
    entity_id  BIGINT NOT NULL REFERENCES entity (id) ON DELETE CASCADE,
    alias      TEXT NOT NULL,                                     -- 哲宗 / 哲廟 / 德完君 같은 표기
    lang       TEXT,
    UNIQUE (entity_id, alias)
);
CREATE INDEX IF NOT EXISTS ix_entity_alias_alias ON entity_alias (alias);

CREATE TABLE IF NOT EXISTS relation (
    id            BIGSERIAL PRIMARY KEY,
    from_id       BIGINT NOT NULL REFERENCES entity (id) ON DELETE CASCADE,
    relation_type TEXT   NOT NULL,                                -- buried_in / happened_at / mentioned_in / same_as ...
    to_id         BIGINT NOT NULL REFERENCES entity (id) ON DELETE CASCADE,
    source_id     SMALLINT NOT NULL REFERENCES source (id),       -- 이 관계를 알려 준 출처
    article_id    TEXT REFERENCES sillok_article (article_id),    -- 실록이 근거면 기사 번호
    evidence      TEXT,                                           -- 근거 문장
    method        TEXT NOT NULL DEFAULT 'rule'
                  CHECK (method IN ('rule','llm','manual')),      -- 어떻게 만든 관계인지
    confidence    REAL,                                           -- 0~1, 확신 정도
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_relation_from ON relation (from_id, relation_type);
CREATE INDEX IF NOT EXISTS ix_relation_to   ON relation (to_id, relation_type);
```

---

## 4. 이렇게 설계한 이유

| 결정 | 이유 |
|---|---|
| `heritage_chunk`를 새 표로 바꾸지 않고 **확장** | `embed_and_store.py`, 호환 뷰 `heritage_chunks`, `rag.py` 등 기존 코드가 그대로 돌아가요 |
| 실록 기사를 `sillok_article`로 따로 | 기사에는 날짜·왕·한문 원문 등 유산과 다른 항목이 있어서 `heritage`에 억지로 넣으면 어색해요 |
| `text_hanja`와 `summary_kor` 분리 | 한문 원문은 근거로 보존, 한글 요약은 검색용 (원본 보존 원칙) |
| 노드를 `entity`로 통합, 유산은 `heritage_id`로 연결 | 이미 있는 유산 데이터를 복사하지 않고 가리키기만 해요 |
| `UNIQUE (source_id, source_key)` | 출처가 달라도 번호가 겹치지 않고, 같은 인물이 중복 저장되지 않아요 |
| 동일 인물 합치기는 `same_as` 관계로 | 틀렸을 때 관계 행만 지우면 되돌릴 수 있어요 |
| 관계에 `method`, `confidence` | 규칙으로 만든 것과 LLM이 만든 것을 구분하고, 불확실한 건 걸러낼 수 있어요 |

---

## 5. 적용 순서 (제안)

1. 테스트 DB에 위 SQL 실행 → `\d+ 표이름`으로 확인
2. `load_sillok.py` 작성: `sillok_heritage_articles_clean.csv` → `sillok_article` (기사 번호 기준 중복 방지)
3. 한글 요약 20건 실험 후 `summary_kor` 채우기 → `heritage_chunk`에 기사 청크 임베딩
4. 이 단계까지가 **RAG(1단계)**. `entity`/`relation`은 비워 둠
5. 3단계에서 실록 인명(`M_...`)을 `entity`(person)로 적재, `relation` 생성
6. `weather_record`는 XLS 확인 후 컬럼 확정

## 6. 아직 정해지지 않은 것 / 미검증

- `PERSON_API`가 어떤 API인지, 실록 `M_` ID와 맞는지
- 기상 XLS의 컬럼 (기사 번호·날짜 유무)
- `sillok_article.source_url` 형식이 실제로 열리는지
- 위 SQL 전체 (실제 DB에서 실행 검증 안 함)
- 기존 `rag.py`가 실록 청크를 검색 대상에 넣을지 (호환 뷰는 `heritage`와 JOIN하므로 기사 청크는 보이지 않음 → 검색 쪽 수정 필요)

## 핵심 정리

- 새로 갈아엎지 않고 **source에 코드 추가 + 실록·기상 표 추가 + 노드/관계 표 추가**.
- `heritage_chunk`는 유산 또는 실록 기사를 가리키도록 확장.
- 노드/관계 표는 3단계 전까지 비워 둬도 됨.
