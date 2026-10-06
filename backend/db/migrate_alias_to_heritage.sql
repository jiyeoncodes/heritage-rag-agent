-- migrate_alias_to_heritage.sql
-- ------------------------------------------------------------
-- heritage_alias 표의 영어·일본어·중국어 이름을 heritage 표의 새 컬럼(name_en / name_ja / name_zh)으로 옮겨요.
--
-- 왜 합치나요?
--   유산 1건에 언어별 이름이 하나씩뿐이고(en/ja/zh), 검색 코드도 이 표를 읽지 않아서
--   따로 표를 두는 것보다 heritage에 컬럼으로 두는 편이 단순해요.
--
-- 안전장치 (하나라도 어긋나면 에러를 내고 전체가 취소돼요. 한 트랜잭션이라 "반만 옮겨진" 상태가 안 생겨요):
--   1) lang이 en/ja/zh가 아닌 별칭이 있으면 중단 (옮길 컬럼이 없어서 데이터가 사라질 수 있어요)
--   2) 같은 유산·같은 언어에 별칭이 2개 이상이면 중단 (컬럼에는 하나만 들어가요)
--   3) 옮긴 뒤 언어별 건수가 원래 건수와 같은지 확인하고, 다르면 중단
--   4) 문제가 없을 때만 heritage_alias를 지우지 않고 heritage_alias_old로 "이름만 바꿔" 보관해요.
--      (며칠 쓰다가 이상이 없으면 DROP TABLE heritage_alias_old; 로 지우세요)
--
-- 실행 방법 (Windows cmd, backend 폴더에서. 순서: schema.sql -> 이 파일):
--   docker exec -i 컨테이너이름 psql -U postgres -v ON_ERROR_STOP=1 < db\schema.sql
--   docker exec -i 컨테이너이름 psql -U postgres -v ON_ERROR_STOP=1 < db\migrate_alias_to_heritage.sql
--
-- 여러 번 실행해도 안전해요. (heritage_alias가 이미 없으면 "옮길 것이 없다"고 알려 주고 끝나요)
-- ------------------------------------------------------------

BEGIN;

ALTER TABLE heritage ADD COLUMN IF NOT EXISTS name_en TEXT;
ALTER TABLE heritage ADD COLUMN IF NOT EXISTS name_ja TEXT;
ALTER TABLE heritage ADD COLUMN IF NOT EXISTS name_zh TEXT;

DO $$
DECLARE
    n_other  INT;   -- en/ja/zh가 아닌 언어의 별칭 수
    n_dup    INT;   -- 같은 유산·같은 언어에 별칭이 2개 이상인 경우의 수
    a_en INT; a_ja INT; a_zh INT;   -- heritage_alias 쪽 언어별 건수
    h_en INT; h_ja INT; h_zh INT;   -- 옮긴 뒤 heritage 쪽에서 값이 같은 건수
BEGIN
    IF to_regclass('public.heritage_alias') IS NULL THEN
        RAISE NOTICE 'heritage_alias 표가 없어요. 옮길 것이 없으니 건너뛰어요. (이미 합친 DB)';
        RETURN;
    END IF;

    -- 안전 점검 1
    SELECT count(*) INTO n_other FROM heritage_alias WHERE lang IS NULL OR lang NOT IN ('en', 'ja', 'zh');
    IF n_other > 0 THEN
        RAISE EXCEPTION 'en/ja/zh가 아닌 별칭이 %건 있어요. 옮기면 데이터가 사라질 수 있어 중단합니다.', n_other;
    END IF;

    -- 안전 점검 2
    SELECT count(*) INTO n_dup
      FROM (SELECT 1 FROM heritage_alias GROUP BY heritage_id, lang HAVING count(*) > 1) d;
    IF n_dup > 0 THEN
        RAISE EXCEPTION '같은 유산·같은 언어에 별칭이 2개 이상인 경우가 %곳 있어요. 컬럼에는 하나만 들어가서 중단합니다.', n_dup;
    END IF;

    -- 옮기기 (이미 값이 있는 칸은 덮어쓰지 않아요)
    UPDATE heritage h SET name_en = a.alias FROM heritage_alias a
     WHERE a.heritage_id = h.id AND a.lang = 'en' AND h.name_en IS NULL;
    UPDATE heritage h SET name_ja = a.alias FROM heritage_alias a
     WHERE a.heritage_id = h.id AND a.lang = 'ja' AND h.name_ja IS NULL;
    UPDATE heritage h SET name_zh = a.alias FROM heritage_alias a
     WHERE a.heritage_id = h.id AND a.lang = 'zh' AND h.name_zh IS NULL;

    -- 안전 점검 3: 언어별로 "원래 건수 = 옮겨진(값이 같은) 건수" 인지 확인
    SELECT count(*) INTO a_en FROM heritage_alias WHERE lang = 'en';
    SELECT count(*) INTO a_ja FROM heritage_alias WHERE lang = 'ja';
    SELECT count(*) INTO a_zh FROM heritage_alias WHERE lang = 'zh';
    SELECT count(*) INTO h_en FROM heritage_alias a JOIN heritage h ON h.id = a.heritage_id WHERE a.lang = 'en' AND h.name_en = a.alias;
    SELECT count(*) INTO h_ja FROM heritage_alias a JOIN heritage h ON h.id = a.heritage_id WHERE a.lang = 'ja' AND h.name_ja = a.alias;
    SELECT count(*) INTO h_zh FROM heritage_alias a JOIN heritage h ON h.id = a.heritage_id WHERE a.lang = 'zh' AND h.name_zh = a.alias;
    IF a_en <> h_en OR a_ja <> h_ja OR a_zh <> h_zh THEN
        RAISE EXCEPTION '옮긴 건수가 맞지 않아요 (en %/%, ja %/%, zh %/%). 중단합니다.', h_en, a_en, h_ja, a_ja, h_zh, a_zh;
    END IF;

    -- 문제가 없을 때만 원래 표를 보관용 이름으로 바꿔요. (바로 지우지 않아요)
    IF to_regclass('public.heritage_alias_old') IS NOT NULL THEN
        RAISE EXCEPTION 'heritage_alias_old 표가 이미 있어요. 먼저 확인하고 지운 뒤 다시 실행하세요.';
    END IF;
    ALTER TABLE heritage_alias RENAME TO heritage_alias_old;
    RAISE NOTICE '옮기기 완료: en % / ja % / zh % 건. 원래 표는 heritage_alias_old로 보관 중이에요.', a_en, a_ja, a_zh;
END $$;

COMMENT ON COLUMN heritage.name_en IS '영어 이름: 궁궐·종묘 API 데이터만 값이 있음. 없으면 NULL';
COMMENT ON COLUMN heritage.name_ja IS '일본어 이름: 궁궐·종묘 API 데이터만 값이 있음. 없으면 NULL';
COMMENT ON COLUMN heritage.name_zh IS '중국어 이름: 궁궐·종묘 API 데이터 중 일부만 값이 있음. 없으면 NULL';

COMMIT;

-- 결과 확인: 아래 숫자가 (en 127 / ja 127 / zh 67, 이름이 있는 유산 127)이면 옮기기 성공이에요.
\echo '===== 확인: heritage 컬럼에 채워진 건수 ====='
SELECT count(name_en) AS name_en, count(name_ja) AS name_ja, count(name_zh) AS name_zh,
       count(*) FILTER (WHERE name_en IS NOT NULL OR name_ja IS NOT NULL OR name_zh IS NOT NULL) AS heritage_with_names
  FROM heritage;
\echo '===== 확인: 광화문 ====='
SELECT id, name_kor, name_en, name_ja, name_zh FROM heritage WHERE name_kor = '광화문' AND group_name = '경복궁';
