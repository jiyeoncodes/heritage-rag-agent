-- inspect_samples.sql
-- ------------------------------------------------------------
-- DB에 실제로 들어 있는 값을 "읽기만" 해서 보여 주는 점검용 스크립트예요. (SELECT만 있어서 데이터는 바뀌지 않아요)
-- 노션 "DB 스키마" 페이지의 예시 값을 실제 DB 값으로 바꾸는 데 쓰려고 만들었어요.
--
-- 실행 방법 (Windows cmd, backend 폴더에서):
--   docker ps                                  <- 컨테이너 이름 확인 (heritage-pg 또는 postgres)
--   docker exec -i 컨테이너이름 psql -U postgres < db\inspect_samples.sql > db\inspect_result.txt
-- 그다음 db\inspect_result.txt 내용을 붙여 넣어 주세요.
-- ------------------------------------------------------------
\pset pager off
\pset null '(NULL)'

\echo '===== 1. 표/뷰 종류 (r=표, v=뷰) ====='
SELECT relname, relkind FROM pg_class
 WHERE relname IN ('source','heritage','heritage_chunk','heritage_alias','media','raw_document','ingest_run','heritage_chunks')
 ORDER BY relname;

\echo '===== 2. 표별 행 수 ====='
SELECT 'source' AS t, count(*) FROM source
UNION ALL SELECT 'heritage', count(*) FROM heritage
UNION ALL SELECT 'heritage_chunk', count(*) FROM heritage_chunk
UNION ALL SELECT 'heritage_alias', count(*) FROM heritage_alias
UNION ALL SELECT 'media', count(*) FROM media
UNION ALL SELECT 'raw_document', count(*) FROM raw_document
UNION ALL SELECT 'ingest_run', count(*) FROM ingest_run;

\echo '===== 3. 실제 컬럼 목록 (스키마 문서와 대조용) ====='
SELECT table_name, ordinal_position AS no, column_name, data_type
  FROM information_schema.columns
 WHERE table_schema = 'public'
   AND table_name IN ('source','heritage','heritage_chunk','heritage_alias','media','raw_document','ingest_run')
 ORDER BY table_name, ordinal_position;

\echo '===== 4. source 전체 ====='
\x on
SELECT * FROM source ORDER BY id;

\echo '===== 5. heritage 예시 (광화문 / 구리 동구릉 / 경복궁 개요) ====='
SELECT * FROM heritage
 WHERE (name_kor = '광화문' AND group_name = '경복궁')
    OR name_kor = '구리 동구릉'
    OR (name_kor = '개요' AND group_name = '경복궁')
 ORDER BY id;

\echo '===== 6. heritage_chunk 예시 (본문과 벡터는 앞부분만) ====='
SELECT c.id, c.heritage_id, c.source_id, c.chunk_type, c.chunk_no,
       left(c.chunk_text, 80) AS chunk_text_head, length(c.chunk_text) AS chunk_text_len,
       c.content_hash, c.embedding_model,
       left(c.embedding::text, 60) AS embedding_head, vector_dims(c.embedding) AS embedding_dims,
       c.created_at, c.updated_at
  FROM heritage_chunk c JOIN heritage h ON h.id = c.heritage_id
 WHERE (h.name_kor = '광화문' AND h.group_name = '경복궁') OR h.name_kor = '구리 동구릉'
 ORDER BY c.id;

\echo '===== 7. heritage_alias 예시 (광화문) ====='
\x off
SELECT a.* FROM heritage_alias a JOIN heritage h ON h.id = a.heritage_id
 WHERE h.name_kor = '광화문' AND h.group_name = '경복궁' ORDER BY a.id;

\echo '===== 8. media 예시 (광화문) ====='
SELECT m.* FROM media m JOIN heritage h ON h.id = m.heritage_id
 WHERE h.name_kor = '광화문' AND h.group_name = '경복궁' ORDER BY m.media_type, m.sort_order;

\echo '===== 9. ingest_run 전체 ====='
SELECT * FROM ingest_run ORDER BY id;

\echo '===== 10. raw_document 앞 3건 ====='
SELECT * FROM raw_document ORDER BY id LIMIT 3;

\echo '===== 11. 광화문의 parent_id 가 가리키는 행 ====='
SELECT h.id, h.parent_id, p.id AS parent_row_id, p.group_name AS parent_group, p.name_kor AS parent_name
  FROM heritage h LEFT JOIN heritage p ON p.id = h.parent_id
 WHERE h.name_kor = '광화문' AND h.group_name = '경복궁';

\echo '===== 12. heritage_alias 가 가진 언어/건수 ====='
SELECT lang, count(*) FROM heritage_alias GROUP BY lang ORDER BY lang;
SELECT count(*) AS heritage_with_alias FROM (SELECT DISTINCT heritage_id FROM heritage_alias) x;
