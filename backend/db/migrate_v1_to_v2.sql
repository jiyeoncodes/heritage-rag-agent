-- migrate_v1_to_v2.sql
-- ------------------------------------------------------------
-- v1의 heritage_chunks "표" 하나에 들어 있던 데이터를 v2의 여러 표로 옮기는 스크립트입니다.
--
-- 실행 순서 (반드시 이 순서로):
--   1) schema.sql              (새 표를 만들어요)
--   2) migrate_v1_to_v2.sql    (이 파일: 데이터를 옮겨요)
--
--   docker exec -i postgres psql -U postgres -v ON_ERROR_STOP=1 < schema.sql
--   docker exec -i postgres psql -U postgres -v ON_ERROR_STOP=1 < migrate_v1_to_v2.sql
--
-- 무엇을 하나요?
--   1. 옛 표 heritage_chunks 의 이름을 heritage_chunks_v1 로 바꿔 "백업"으로 남겨요. (지우지 않아요)
--   2. 유산 -> heritage, 본문+벡터 -> heritage_chunk, 이미지·동영상 -> media 로 복사해요.
--      (벡터는 다시 만들지 않고 그대로 복사하므로 Gemini API를 호출하지 않아요.)
--   3. 건물·시설 행에 소속 궁 개요를 상위 유산(parent_id)으로 연결해요.
--   4. (예전에는 호환용 뷰 heritage_chunks를 만들었지만, 지금은 만들지 않아요. 검색 코드가 v2 표를 직접 읽어요.)
--   5. 건수가 맞는지 확인하고, 안 맞으면 오류를 내고 전부 취소(롤백)해요.
--
-- 안전장치:
--   - 하나의 트랜잭션이라 중간에 오류가 나면 아무것도 바뀌지 않아요.
--   - 이미 옮긴 DB(heritage_chunks가 뷰)에서 다시 실행하면 아무것도 하지 않고 넘어가요.
--   - 백업(heritage_chunks_v1)은 결과를 확인한 뒤 직접 지우세요:  DROP TABLE heritage_chunks_v1;
-- ------------------------------------------------------------

DO $$
DECLARE
    v1_kind     "char";
    v1_count    BIGINT;
    n_heritage  BIGINT;
    n_chunk     BIGINT;
    n_image     BIGINT;
    n_video     BIGINT;
    exp_image   BIGINT;
    exp_video   BIGINT;
    n_parent    BIGINT;
BEGIN
    -- 0. 지금 heritage_chunks 가 "표(r)"인지 확인해요. 뷰나 없음이면 옮길 게 없어요.
    SELECT relkind INTO v1_kind FROM pg_class WHERE oid = to_regclass('heritage_chunks');
    IF v1_kind IS DISTINCT FROM 'r' THEN
        RAISE NOTICE '옮길 v1 표가 없어요 (이미 옮겼거나 새 DB). 아무것도 하지 않고 넘어갑니다.';
        RETURN;
    END IF;
    IF to_regclass('heritage') IS NULL THEN
        RAISE EXCEPTION 'schema.sql(v2)을 먼저 실행하세요. heritage 표가 없어요.';
    END IF;
    IF EXISTS (SELECT 1 FROM heritage) THEN
        RAISE EXCEPTION 'heritage 표에 이미 데이터가 있어요. 중복 이전을 막으려고 중단합니다. 상태를 확인하세요.';
    END IF;

    -- 종합 API 행(지정번호가 있는 행)은 전부 사적(코드 13)이어야 안전하게 종목 코드를 채울 수 있어요.
    IF EXISTS (SELECT 1 FROM heritage_chunks WHERE ccba_asno IS NOT NULL AND designation IS DISTINCT FROM '사적') THEN
        RAISE EXCEPTION '사적이 아닌 종합 API 행이 있어요. 종목 코드를 자동으로 정할 수 없어 중단합니다.';
    END IF;

    SELECT count(*) INTO v1_count FROM heritage_chunks;

    -- 1. 옛 표를 백업 이름으로 바꿔요.
    ALTER TABLE heritage_chunks RENAME TO heritage_chunks_v1;

    -- 2-a. 출처: v1에 적힌 출처 이름 중 source 표에 없는 것만 추가해요.
    INSERT INTO source (name)
    SELECT DISTINCT s FROM (
        SELECT COALESCE(source, CASE WHEN ccba_asno IS NULL THEN '국가유산청 궁궐·종묘 Open API'
                                     ELSE '국가유산청 국가유산 종합 Open API' END) AS s
          FROM heritage_chunks_v1
    ) t
    ON CONFLICT (name) DO NOTHING;

    -- 2-b. 유산 (v1 id 순서를 유지해서 넣어요)
    INSERT INTO heritage (ccba_kdcd, ccba_asno, gung_number, serial_number, detail_code,
                          group_name, name_kor, entity_type, designation, created_at, updated_at)
    SELECT CASE WHEN ccba_asno IS NOT NULL THEN '13' END,      -- 지금까지 종합 API로 넣은 것은 전부 사적(13)
           ccba_asno, gung_number, serial_number, detail_code,
           gung_name, contents_kor,
           COALESCE(heritage_type, '건물·시설'),
           designation, created_at, updated_at
      FROM heritage_chunks_v1
     ORDER BY id;

    -- 2-c. 글 덩어리 + 벡터 (v1 행과 새 heritage 행을 키로 짝지어요)
    INSERT INTO heritage_chunk (heritage_id, source_id, chunk_type, chunk_no, chunk_text, content_hash,
                                embedding_model, embedding, created_at, updated_at)
    SELECT h.id,
           s.id,
           CASE COALESCE(v.heritage_type, '건물·시설')
                WHEN '개요' THEN '개요'
                WHEN '능역' THEN '지정 설명'
                ELSE '건물 해설' END,
           1,
           v.chunk_text,
           md5(v.chunk_text),
           v.embedding_model,
           v.embedding,
           v.created_at, v.updated_at
      FROM heritage_chunks_v1 v
      JOIN heritage h
        ON (v.ccba_asno IS NOT NULL AND h.ccba_kdcd = '13' AND h.ccba_asno = v.ccba_asno)
        OR (v.ccba_asno IS NULL AND h.ccba_asno IS NULL
            AND h.gung_number = v.gung_number AND h.serial_number = v.serial_number
            AND h.detail_code = v.detail_code)
      JOIN source s
        ON s.name = COALESCE(v.source, CASE WHEN v.ccba_asno IS NULL THEN '국가유산청 궁궐·종묘 Open API'
                                            ELSE '국가유산청 국가유산 종합 Open API' END)
     ORDER BY v.id;

    -- 2-d. 대표 이미지 (비어 있지 않은 것만)
    INSERT INTO media (heritage_id, media_type, url, sort_order)
    SELECT h.id, 'image', btrim(v.img_url), 0
      FROM heritage_chunks_v1 v
      JOIN heritage h
        ON (v.ccba_asno IS NOT NULL AND h.ccba_kdcd = '13' AND h.ccba_asno = v.ccba_asno)
        OR (v.ccba_asno IS NULL AND h.ccba_asno IS NULL
            AND h.gung_number = v.gung_number AND h.serial_number = v.serial_number
            AND h.detail_code = v.detail_code)
     WHERE btrim(COALESCE(v.img_url, '')) <> ''
    ON CONFLICT (heritage_id, url) DO NOTHING;

    -- 2-e. 동영상 (세미콜론으로 이어 붙인 값을 한 줄씩 펼쳐요)
    INSERT INTO media (heritage_id, media_type, url, sort_order)
    SELECT h.id, 'video', btrim(u.url), (u.ord - 1)::int
      FROM heritage_chunks_v1 v
      JOIN heritage h
        ON (v.ccba_asno IS NOT NULL AND h.ccba_kdcd = '13' AND h.ccba_asno = v.ccba_asno)
        OR (v.ccba_asno IS NULL AND h.ccba_asno IS NULL
            AND h.gung_number = v.gung_number AND h.serial_number = v.serial_number
            AND h.detail_code = v.detail_code)
      CROSS JOIN LATERAL unnest(string_to_array(v.moving_urls, ';')) WITH ORDINALITY AS u(url, ord)
     WHERE btrim(COALESCE(v.moving_urls, '')) <> '' AND btrim(u.url) <> ''
    ON CONFLICT (heritage_id, url) DO NOTHING;

    -- 3. 상위 유산 연결: 건물·시설 -> 같은 분류명의 개요 행
    --    이 UPDATE가 수정시간을 "지금"으로 바꾸지 않도록, 트리거를 잠깐 꺼요. (v1의 수정시간을 그대로 보존)
    ALTER TABLE heritage DISABLE TRIGGER trg_heritage_updated_at;
    UPDATE heritage b
       SET parent_id = p.id
      FROM heritage p
     WHERE b.entity_type = '건물·시설' AND p.entity_type = '개요'
       AND p.group_name = b.group_name AND b.parent_id IS NULL;
    ALTER TABLE heritage ENABLE TRIGGER trg_heritage_updated_at;

    -- 4. (삭제) 호환용 뷰는 더 이상 만들지 않아요. 검색 코드가 v2 표를 직접 읽어요.

    -- 5. 검증: 건수가 맞아야 해요.
    SELECT count(*) INTO n_heritage FROM heritage;
    SELECT count(*) INTO n_chunk    FROM heritage_chunk;
    IF n_heritage <> v1_count OR n_chunk <> v1_count THEN
        RAISE EXCEPTION '건수 불일치: v1=% / heritage=% / chunk=% (전부 취소됩니다)', v1_count, n_heritage, n_chunk;
    END IF;

    SELECT count(*) INTO exp_image FROM heritage_chunks_v1 WHERE btrim(COALESCE(img_url, '')) <> '';
    SELECT count(*) INTO n_image   FROM media WHERE media_type = 'image';
    IF n_image <> exp_image THEN
        RAISE EXCEPTION '이미지 건수 불일치: 기대 % / 실제 % (전부 취소됩니다)', exp_image, n_image;
    END IF;

    SELECT count(*) INTO n_video FROM media WHERE media_type = 'video';
    SELECT count(*) INTO exp_video
      FROM heritage_chunks_v1 v
      CROSS JOIN LATERAL unnest(string_to_array(v.moving_urls, ';')) AS u(url)
     WHERE btrim(COALESCE(v.moving_urls, '')) <> '' AND btrim(u.url) <> '';
    IF n_video <> exp_video THEN
        RAISE EXCEPTION '동영상 건수 불일치: 기대 % / 실제 % (전부 취소됩니다)', exp_video, n_video;
    END IF;

    SELECT count(*) INTO n_parent FROM heritage WHERE parent_id IS NOT NULL;
    RAISE NOTICE '이전 완료: 유산 % / 글 덩어리 % / 이미지 % / 동영상 % / 상위 유산 연결 %건',
                 n_heritage, n_chunk, n_image, n_video, n_parent;
END $$;
