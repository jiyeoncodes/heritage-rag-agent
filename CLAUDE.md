# heritage-rag-agent 프로젝트 가이드

> 이 문서는 이 프로젝트에 대해 작업할 때(특히 Claude Code 등 AI 도구를 쓸 때) 읽는
> 배경 지식 문서입니다. 프로젝트 루트(`C:\project\heritage-rag-agent`)에 두세요.
> 마지막 갱신: 2026-10-06

---

## 1. 프로젝트 개요

**이름**: heritage-rag-agent
**한 줄 소개**: 조선 왕릉ㆍ궁궐 문화유산을 RAG(검색 기반 답변) + Agent + 관계 탐색으로
탐색하는 개인 프로젝트

**만드는 사람**: AI 엔지니어 취업을 준비 중인 부트캠프 학습자. 파이썬 중심으로 학습 중이며
코딩 초보 수준. AI 엔지니어 실무 역량(RAG, Agent, 벡터DB, 프롬프트 설계)을 포트폴리오로
증명하는 것이 목표.

**핵심 컨셉**: 단순히 "질문하면 답하는 챗봇"이 아니라, 질문을 받으면 DB·문헌·관계 정보를
탐색해서 **관련 유산ㆍ인물ㆍ사건ㆍ지역까지 함께 보여주는 탐색형 서비스**를 지향함.

```
사용자 질문
     │
   AI Agent
 ┌───┼───┐
 DB  문헌  관계 검색
 └───┼───┘
  정보 통합
     │
 답변 + 관련 유산 + 관계 그래프
```

**단계별 로드맵**: RAG(1단계) → Agent(2단계) → 관계 탐색(3단계) → 멀티모달(4단계) 순서로
"작게 시작해서 확장"하는 전략을 취함. 각 단계가 끝날 때마다 동작하는 결과물을 남겨서,
중간에 끊겨도 포트폴리오로 제출 가능하게 함.

**1단계 범위**: 조선 왕릉ㆍ궁궐 (전체 문화유산이 아니라 주제 하나로 좁혀서 시작)

**현재 위치 (2026-10-06)**: 1단계의 **질문 단계(검색 → LLM 답변 → 출처 표시)가 화면까지 end-to-end로 동작**함
(백엔드 `rag.py`/`main.py` 실제 기동 확인, React+TS 프론트 화면 정상 확인).
**데이터 범위 보강도 DB에 반영됨**: 기존 궁궐·종묘 127 + 조선왕릉 18개 능역 + 경희궁지 1 + 5대 궁궐 개요 5 = **151건**(2026-10-04 DB 직접 조회).
**평가 갱신은 2026-10-06에 완료**(검색 29문항 MRR 0.89, 환각 7/7 거절 — 6장 3-1~3-4 참고). **1단계에 남은 것은 하이브리드 검색(3-6: "문정전" 이름 겹침 문제), 코드 중복 정리, git 푸시**예요. 그 뒤 1단계 완료.

---

## 2. 기술 스택

| 영역 | 선택 | 비고 |
|---|---|---|
| 프론트엔드 | React 19 + TypeScript + Vite 8 | 질문 입력·답변·출처 카드 화면 완성, 사용자 PC에서 정상 표시 확인. 일반 CSS(라이트/다크 자동), 린터 oxlint |
| 백엔드 | Python + FastAPI | `backend/rag.py`, `backend/main.py`. 가짜 Gemini/DB로 35개 시험 통과 + **사용자 PC에서 실제 기동·`/api/health`·`/docs` 확인 완료** |
| 벡터 DB | PostgreSQL + pgvector | Windows, Docker로 설치 완료 (`docker/docker-compose.yml`, 컨테이너 이름 `postgres`) |
| 임베딩 모델 | Gemini `gemini-embedding-001` (768차원) | 무료 티어 사용, GCP 무료 VM(1GB RAM)에서 자체 모델 구동이 불가능해 API 방식으로 결정 |
| LLM | **확정: 기본 `gemini-3.5-flash-lite`, 예비 `gemini-3.1-flash-lite`** | 아래 "LLM 확정 근거" 참고. 모델은 `backend/.env`의 `LLM_MODEL`로만 바꿈 |
| 배포(예정) | GCP Compute Engine `e2-micro` (Always Free) | 지역: `us-west1`/`us-central1`/`us-east1` 중 하나. 1GB RAM이라 AI 연산은 전부 외부 API로 처리 |

**결정 이유 메모**:
- 벡터 DB 인덱스(HNSW)는 pgvector에서 최대 2,000차원까지 직접 지원 → 768차원이면 여유 있음.
- 임베딩은 문서 저장 시 `task_type="RETRIEVAL_DOCUMENT"`, 사용자 질문은 `task_type="RETRIEVAL_QUERY"`를 사용 (구현·검증 완료).
- LangChain 같은 프레임워크는 **1단계에서는 일부러 쓰지 않음**: 검색·프롬프트·호출의 원리를 직접 보고 이해하는 것이 목표.
  2단계(Agent)에서 LangChain/LangGraph 도입을 검토.

### LLM 확정 근거 (2026-10-03)

- 같은 21문항(정답 있는 15 + 환각 6)에서 두 모델이 **동점** (정답 출처 선택 15/15, 환각 거절 6/6, 원문과 대조한 사실 주장 모두 근거 있음).
- 품질로 가를 수 없어서, ① 기본/예비로 쓰면 **무료 한도가 합산**되고(한도는 모델별로 따로 셈), ② 3.5가 더 최신 세대이고(오래된 모델은 순서대로
  신규 사용자에게 막히는 경향 — 예상일 뿐 보장은 아님), ③ 이미 3.5로 설정·기준선을 만들었으므로 3.5를 기본으로 확정.
- **임시 확정**: 데이터가 늘고 평가 질문이 많아져 차이가 보이면 `.env` 한 줄로 교체.

### Gemini 무료 티어 한도 (중요)

- 하루 요청 한도가 **모델별·프로젝트별**로 계산됨(키를 새로 만들어도 늘지 않음). 초기화는 태평양 시간 자정(한국 시간 오후 4시경, 11월 초 서머타임 종료 후 5시경).
- 제3자 실측(2026-09): **Flash 계열(3.8/3.7/3.6/3.5-flash)은 약 20회/일, Flash-Lite 계열(3.5/3.1-flash-lite)은 약 500회/일**, 임베딩은 약 1,000회/일.
  Google이 공식 문서에서 숫자를 더 이상 공개하지 않으므로 **AI Studio 사용량 화면(https://aistudio.google.com/rate-limit)에서 직접 확인**할 것.
- 오류 구분: `429 + PerDay` = 하루 한도(기다려도 안 풀림 → 다른 모델 사용 / 다음 날), `429 + 분당` = 잠깐 기다리면 풀림, `503` = 서버 일시 혼잡(재시도), `404` = 모델 이름 오류.
- 모델 이름은 자주 바뀜(예: `gemini-2.5-flash`는 신규 사용자에게 더 이상 제공되지 않아 404). 404가 나면 https://ai.google.dev/gemini-api/docs/models 에서 현재 이름 확인.

### 답변 프롬프트 규칙 (SYSTEM_INSTRUCTION, 평가로 검증됨)

참고 자료에 적힌 내용만 근거로 답하고, ① 근거가 없으면 "제공된 자료에서는 확인할 수 없습니다." 한 문장만 쓰며 출처 줄도 쓰지 않고,
② 자료에 없는 표현(예: "정문")은 자료의 설명으로 추론하되 "자료상 ~로 보입니다"로 추론임을 밝히고, "명시되어 있다"고 쓰지 않으며,
③ 답은 3~5문장, 끝에 `출처: [궁 이름 유산명]`을 적는다. 전문은 `backend/rag.py`(서버용)와 `backend/scripts/answer_test.py`(평가용)에 **같은 내용으로 두 곳**
있으므로, 고칠 때는 두 곳을 함께 고칠 것 (나중에 한곳으로 통합 예정).

---

## 3. 데이터 범위와 출처

### 현재 수집 중인 데이터: 국가유산청 궁궐ㆍ종묘 API

- 제공처: 국가유산포털 (heritage.go.kr)
- 인증키: 불필요 (API 유형이 LINK이며, 실제로 키 없이 127건 호출 성공 확인함)
- 응답 형식: XML (CDATA로 텍스트 감싸져 있음)
- 이용 조건: 공공저작물, 출처 표시 시 자유 이용 가능

| API | 주소 | 파라미터 |
|---|---|---|
| 목록조회 | `https://www.heritage.go.kr/heri/gungDetail/gogungListOpenApi.do` | `gung_number` (1~5) |
| 상세조회 | `https://www.heritage.go.kr/heri/gungDetail/gogungDetailOpenApi.do` | `serial_number`, `gung_number`, `detail_code` — 목록조회 응답의 `<link>` 필드에 이미 완성된 주소로 들어있어 그대로 재사용 가능 |

**궁 번호 매핑**: `1=경복궁, 2=창덕궁, 3=창경궁, 4=덕수궁, 5=종묘`

### ✅ 데이터 공백 해소 (2026-10-04 DB 조회로 확인)

| 항목 | 상태 |
|---|---|
| **경희궁** | 궁궐 API에는 없지만 **국가유산청 '국가유산 종합 Open API'에 `경희궁지`(사적 제271호)로 있어** 수집·임베딩 완료 (개요 1건뿐이고 건물별 설명은 없음) |
| **조선 왕릉** | 같은 종합 API의 **사적 "능역" 18건**을 수집·임베딩 완료 (아래 참고). "40기"가 아니라 **능역 18건 단위**이며, 릉별 40기 단위는 별도 출처가 필요하고 아직 못 찾음 |

#### 새 출처: 국가유산청 국가유산 종합 Open API (2026-10-03 조사)

- 인증키 **불필요** (키 없이 목록·상세 호출 성공을 확인함 — 다만 확인은 웹 조회 도구로 했고, 사용자 PC의 `requests`로는 아직 안 해봄)
- 목록: `https://www.khs.go.kr/cha/SearchKindOpenapiList.do` / 상세: `https://www.khs.go.kr/cha/SearchKindOpenapiDt.do`
- 주요 파라미터: `ccbaKdcd`(종목 코드, **사적=13**), `ccbaMnm1`(이름 검색), `ccbaAsno`(지정번호), `ccbaCtcd`(시도 코드), `pageUnit`(한 번에 가져올 건수)
- ⚠️ 상세 조회의 `ccbaAsno`는 **목록 응답에 나온 13자리 값 그대로** 넣어야 함. 8자리(`02710000`)로 넣으면 오류 없이 **빈 응답**이 와서 헷갈림.
- 상세 응답에 있는 것: 명칭(한/한자), 종목, 분류, 소재지, 시대, 면적, 지정일, 관리자, 경위도, `imageUrl`, `content`(설명글, 경희궁지 약 580자 · 동구릉 약 900자 · 헌릉과 인릉 약 1,100자)
- 이용 조건/출처 표기 문구는 응답에 없음 → 국가유산청(khs.go.kr) 자료로 **출처를 표시**할 것 (기존 궁궐 API와 같은 방침)

**조선왕릉 18개 능역(사적)** — 목록에서 `ccbaMnm1`에 "릉"이 들어간 66건 중 조선왕릉만 골라야 함 (신라·백제·고려 왕릉이 섞여 있음):
동구릉, 헌릉과 인릉, 영릉과 영릉(세종·효종), 영월 장릉, 광릉, 서오릉, 선릉과 정릉, 서삼릉, 태릉과 강릉, 김포 장릉, 파주 장릉, 의릉, 파주 삼릉, 융릉과 건릉, 홍릉과 유릉, 정릉, 사릉, 온릉.
(`고양 공양왕릉`, `강화 홍릉·석릉·가릉·곤릉`, `연천 경순왕릉`, 경주·김해·부여 등은 조선왕릉이 **아니므로 제외**)

**알아둘 점 / 결정이 필요한 점**
- 한 건이 릉 1기가 아니라 **능역 단위**임 (동구릉 = 9기가 한 건). 그래서 이 API만으로는 "왕릉 40기"가 아니라 "능역 18건"이 됨. 40기 단위로 쪼개려면 별도 출처가 필요.
- 설명 한 건에 여러 릉 이야기가 섞여 있어 하나의 청크로 넣으면 검색이 "건원릉 누구 무덤이야?" 같은 개별 릉 질문에 약할 수 있음 → 청킹(릉별로 나누기) 여부를 평가로 판단.
- 설명이 900~1,100자로 기존 평균(346자)보다 길지만 임베딩 한도에는 여유 있음.
- 경희궁지는 기존 `[궁이름] 유산명 - 설명글` 형식에 맞춰 궁 이름을 "경희궁"으로 넣으면 기존 파이프라인 재사용 가능.
- 확인하지 못한 것: 조선왕릉 40기를 릉 단위로 제공하는 별도 공공 API(조선왕릉 공식 사이트 등)는 이번 검색에서 찾지 못함.

**수집 스크립트 상태 (2026-10-03)**: `backend/scripts/collect_royal_tombs.py` 작성 완료 → `data/raw/heritage_royal_tombs_detail.csv`(+ 원본 XML은 `data/raw/royal_xml/`).
가짜 XML로 필터·페이지·빈 응답 처리·저장을 시험했고, **사용자 PC에서 실제 실행도 완료**(CSV 24건 생성, DB 반영 확인).
CSV를 pandas로 읽을 때 `ccba_asno`는 앞자리 0이 있는 문자열이라 **`dtype={"ccba_asno": str}`** 로 읽을 것. `content_hash`는 다음 수집 때 설명글이 바뀐 건만 다시 임베딩하기 위한 지문.
**정리·임베딩 스크립트 상태 (2026-10-03)**: `clean_royal_tombs.py` 작성·실행 검증 완료(실제 CSV 19건으로 확인: 태그 0, 명칭변경 안내 0). `embed_and_store.py`를 확장해 두 CSV(궁궐 `gung` / 왕릉·경희궁 `royal`)를 모두 처리하고 `--source all|gung|royal` 옵션 지원.
- DB 저장 규칙: `ccba_asno`=지정번호(왕릉·경희궁·개요), `gung_number/serial_number/detail_code`=NULL. 기존 궁궐 127건은 `ccba_asno`=NULL.
  - 새 컬럼(2026-10-03): `heritage_type`(유산 유형: 건물·시설 / 개요 / 능역), `designation`(지정 종목: 사적 등, 궁궐 API 데이터는 NULL), `source`(출처 기관·API 이름). 기존 행은 `schema.sql`의 UPDATE로 채움.
  - `gung_name`(분류명) / `contents_kor`(유산명): 왕릉 = `조선왕릉` / `영월 장릉`, 경희궁 = `경희궁` / `경희궁지`, **5대 궁궐 개요 = 궁 이름(`창덕궁`) / `개요`** → 출처 표시는 `[창덕궁 개요]`. 건물 항목(`[창덕궁 인정전]`)과 같은 궁 안에서 `heritage_type`으로 구분.
- 이어하기: 궁궐은 (궁 번호, 순번, 세부코드), 왕릉·경희궁은 `ccba_asno`로 "이미 저장됨" 판단. 지정번호가 같은데 본문이 달라졌으면 다시 임베딩해 UPDATE(`updated_at`은 트리거가 자동 갱신).
- 검증: 가짜 DB/Gemini로 신규 19건 저장·재실행 시 전부 건너뜀·본문 변경 시 UPDATE 1건·줄바꿈 차이 무시·실패 시 롤백 시험 통과. **실제 Gemini·PostgreSQL 실행도 사용자 PC에서 완료**: DB에 151건 저장 확인(2026-10-04 조회: heritage 151 · heritage_chunk 151 · media 227).
- 실행 순서(2026-10-03 갱신): `schema.sql` 재적용 → `collect_royal_tombs.py`(24건) → `clean_royal_tombs.py` → `embed_and_store.py` → `SELECT COUNT(*)`가 151인지 확인 (이전 146 + 개요 5). 예전 형식의 `heritage_royal_tombs_detail.csv`/`_clean.csv`는 새 컬럼이 없으므로 반드시 collect부터 다시 실행.
- (이전 메모) 실제 실행 → `SELECT COUNT(*) FROM heritage_chunk;`가 151인지 확인 → `eval_search.py`로 기존 15문항 회귀 확인 → 왕릉·경희궁 평가 질문 추가 → 환각 테스트의 경희궁 문항 기대값 변경.

(이전 메모) 다음 단계 후보: `collect_royal_tombs.py`(목록 → 조선왕릉 18건 + 경희궁지 필터 → 상세 수집 → `data/raw`에 저장) → 정리 → `embed_and_store.py` → `eval_search.py`(회귀 확인).

이전에 언급된 다른 보강 후보: 국가유산청 문화재 공간정보(WFS), 국사편찬위원회 한국사데이터베이스, 조선왕조실록, 우리역사넷.
(데이터가 DB에 들어갔으므로 평가의 "환각 테스트"에서 경희궁·왕릉 문항의 기대값을 바꿔야 함 → 6장 3-3. 초안: `docs/eval_royal_draft.py`)

### DB 현황 (2026-10-04, `db/inspect_samples.sql`로 직접 조회)

표 6개. (옛 호환 뷰 `heritage_chunks`는 2026-10-06에 제거 — 검색 코드가 `heritage_chunk` + `heritage`를 직접 읽음) 컬럼과 실제 값은 Notion "DB 스키마" 페이지에 정리해 둠.

| 표 | 하는 일 | 행 수 |
|---|---|---|
| `source` | 출처 이름·이용 조건·URL | 2 |
| `heritage` | 유산 1건 (영어·일본어·중국어 이름은 `name_en` / `name_ja` / `name_zh` 컬럼) | 151 |
| `heritage_chunk` | 설명글(**청크**) + 임베딩 벡터 (검색 대상) | 151 |
| `media` | 이미지·동영상 주소 | 227 |
| `raw_document` | 수집 원본 위치·해시 (아직 쓰는 코드 없음) | 0 |
| `ingest_run` | 임베딩 실행 기록 (운영 일지) | 1 |
| ~~`heritage_chunks` (뷰)~~ | 제거됨 (rag.py·search_test.py·eval_search.py가 v2 표를 직접 JOIN) | - |

- 151건 = 궁궐·종묘 127 + 조선왕릉 능역 18 + 경희궁지 1 + 5대 궁궐 개요 5.
- **`heritage_alias` 표는 `heritage`에 합침**(`db/migrate_alias_to_heritage.sql`). 사용자가 DB에 적용했다고 알려 줬으나 **결과 숫자는 아직 확인 못 함**
  (기대값: name_en 127 / name_ja 127 / name_zh 67). 원래 표는 `heritage_alias_old`로 보관 중이며, 며칠 써 보고 이상이 없으면 `DROP TABLE heritage_alias_old;`.
- 용어: 검색 대상 글 조각은 **"청크"**로 통일(이전의 "덩어리" 표현 폐기). 시간 값은 DB에 UTC로 저장됨.

### 추가로 모은 데이터 (1단계 이후에 사용, 2026-10-04)

| 데이터 | 상태 | 쓰임 |
|---|---|---|
| 조선왕조실록 원문 XML (공공누리 1유형) | `collect_sillok.py` · `clean_sillok.py` 실행 완료. 왕릉·궁궐 관련 기사 정제본 **6,070건** (`data/processed/sillok_heritage_articles_clean.csv`). **DB에는 아직 안 넣음** | 2단계 문헌 검색 도구, 3단계 인물·사건 그래프 |
| 기상청 조선왕조실록 기상기록 (공공누리 1유형, 12,184행, 태조~성종·세종 전반기) | data.go.kr 페이지만 확인, **파일은 아직 안 받음** | 3단계 사건(재해) 노드 후보. 한글 해설이 있어 한문 문제를 줄여 줌 |
| 인물 API | 어떤 API인지 미정 | 3단계 인물 노드 |

결정·방침 (2026-10-04):
- 실록 원문은 한문이라 한글 질문과 임베딩이 잘 맞을지 **미검증**. 원문은 그대로 보존하고, 검색용으로는 기사 제목 + 한글 요약(`summary_kor`)을 임베딩하는 안을 **20건 샘플로 먼저 비교**.
- 임베딩 무료 한도가 약 1,000회/일이라 6,070건은 **6일 이상** 걸림 → 필요한 만큼만, 서두르지 않음.
- 실록의 인물 ID(`M_...`, 서로 다른 인물 12,164명)는 실록 안에서만 쓰는 번호. 인물 노드는 별도 인물 API를 기준으로 하고 실록은 "관계의 근거 문장"으로 쓴다 (두 ID가 맞는지는 미확인).
- `backend/data/raw/sillok_xml/`(약 961MB)는 git에 올리지 않음 (`.gitignore`에 추가함. GitHub 파일 100MB 제한).
- 3층 구조 설계안(출처 등록표 `source.code` → 출처별 표 → 통합 `entity` / `relation`)은 `docs/db_design_3layer.md`. **아직 적용 전**이며 표는 필요한 시점에 하나씩 추가
  (실록을 RAG에 넣을 때 `sillok_article`, 관계 그래프 단계에 `entity`·`relation`).

---

## 4. 폴더 구조 (2026-10-03 정리 완료)

Python 관련 파일은 모두 `backend/` 안에 있고, `.env`(API 키)도 `backend/`에만 둠. 프론트엔드는 키를 갖지 않음.

```
heritage-rag-agent\
├── backend\
│   ├── main.py             # FastAPI 서버 (POST /api/ask, GET /api/health)
│   ├── rag.py              # 검색(하이브리드) + LLM 답변 + 출처 정리 + 오류 분류
│   ├── hybrid_search.py    # 질문 분류 · 키워드 점수 · 점수 합치기 (순수 계산, DB·API 불필요)
│   ├── requirements.txt
│   ├── .env                # 실제 키 (git 제외)
│   ├── env.example         # .env 템플릿 (이름에 점 없음, git 포함)
│   ├── venv\               # 가상환경 (git 제외)
│   ├── db\
│   │   ├── schema.sql                     # v2 표 정의 (source, heritage, heritage_chunk, media, raw_document, ingest_run)
│   │   ├── migrate_v1_to_v2.sql           # v1(표 하나) → v2 옮기기 (적용 완료)
│   │   ├── migrate_alias_to_heritage.sql  # heritage_alias → heritage.name_en/ja/zh 옮기기 (여러 번 실행해도 안전)
│   │   └── inspect_samples.sql            # DB 내용을 읽기만 하는 점검 스크립트 (결과 inspect_result.txt는 git에 올리지 않아도 됨)
│   ├── data\
│   │   ├── raw\            # 수집 원본 (궁궐 CSV, 왕릉 CSV·royal_xml\, 실록 sillok_xml\·CSV·JSONL) — 항상 보존. sillok_xml은 약 961MB라 git 제외
│   │   ├── processed\      # 정리 완료 CSV (RAG 문서로 바로 사용). 궁궐·왕릉 CSV는 DB 반영됨, sillok_heritage_articles_clean.csv는 아직 미반영
│   │   └── eval\           # 평가 결과 CSV (기준선 비교용으로 보관)
│   └── scripts\            # 데이터 수집ㆍ정리ㆍ임베딩ㆍ검색ㆍ평가 스크립트
│       ├── collect_gung_list.py
│       ├── collect_gung_detail.py
│       ├── clean_gung_detail.py
│       ├── embed_and_store.py
│       ├── collect_royal_tombs.py  # 조선왕릉 18 + 경희궁지 1 + 5대 궁궐 개요 5 = 24건 수집 (국가유산 종합 API, 원본 XML도 보관)
│       ├── clean_royal_tombs.py    # 태그·명칭변경 안내 제거, "[분류명] 유산명 - 설명글" 본문 생성 → data/processed/heritage_royal_tombs_clean.csv
│       ├── collect_sillok.py   # 실록 XML에서 왕릉·궁궐 기사만 골라 data/raw/sillok_heritage_articles.csv/.jsonl 저장 (원본 XML은 건드리지 않음)
│       ├── clean_sillok.py     # 짧은 기사·종묘 제례·일반 용어·정릉동 오탐 제거 → data/processed/sillok_heritage_articles_clean.csv (6,070건)
│       ├── search_test.py      # 질문 → 비슷한 유산 검색 테스트
│       ├── answer_test.py      # 질문 → 검색 → LLM 답변 (한 질문)
│       ├── eval_search.py      # 검색 평가 (15문항, 정답 순위/MRR) — LLM 호출 없음(무료)
│       └── eval_answer.py      # 답변 평가 (정답 15 + 환각 6) — LLM 호출함, 이어하기 지원
├── frontend\               # React + TypeScript + Vite
│   ├── package.json, vite.config.ts(포트 5173 고정), tsconfig*.json, .oxlintrc.json
│   ├── .env.example        # VITE_API_BASE_URL (백엔드 주소, 비밀 정보 넣지 말 것)
│   ├── index.html, public\favicon.svg
│   └── src\
│       ├── main.tsx, App.tsx       # 화면 조립, 요청 상태(idle/loading/success/error) 관리
│       ├── types.ts                # 백엔드 응답 타입 (pydantic 모델과 같은 모양 유지!)
│       ├── api.ts                  # askQuestion(), fetchHealth(), 오류 → 한글 메시지
│       ├── index.css
│       └── components\QuestionForm.tsx, SourceList.tsx
├── docker\
│   └── docker-compose.yml  # PostgreSQL + pgvector
├── .gitignore              # .env, venv, __pycache__, node_modules 등 제외
├── CLAUDE.md               # 이 문서
└── README.md
```

모든 스크립트는 `Path(__file__).resolve().parent.parent`(= `backend/`)를 기준으로 `.env`, `data/`를 찾으므로
**`backend/scripts/`와 `backend/data/`의 상대 위치를 바꾸지 말 것.** `.env`는 `load_dotenv(..., override=True)`로 읽어서,
터미널에 같은 이름의 환경변수가 남아 있어도 **항상 `.env` 값이 우선**함.

---

## 5. 지금까지 완료한 작업

### 데이터 파이프라인
- [x] **주제 확정**: 조선 왕릉ㆍ궁궐로 1단계 범위 좁힘
- [x] **데이터 출처 확인**: 궁궐ㆍ종묘 API(목록조회/상세조회) 구조 파악
- [x] **목록조회 수집** (`collect_gung_list.py`) → `data/raw/heritage_gung_list.csv`
  - 총 **127건** (경복궁 31 · 종묘 28 · 창경궁 27 · 창덕궁 24 · 덕수궁 17)
- [x] **상세조회 수집** (`collect_gung_detail.py`) → `data/raw/heritage_gung_detail.csv`
  - 총 127건, 4개 언어(한/영/일/중) 명칭·설명, 대표 이미지, 동영상 URL 포함, 실패 0건
  - API 문서와 다른 점 3가지 발견 및 대응: `<moving>` 여러 개(`findall`, `;`로 연결) / `<image>`가 아니라 `<listImg>` 컨테이너 / 설명 중간의 `<br/>`(67건)
- [x] **데이터 정리** (`clean_gung_detail.py`) → `data/processed/heritage_gung_detail_clean.csv`
  - `<br/>` 등 HTML 태그 제거, `explanation_kor_length` 추가(최소 35자 · 평균 346자 · 최대 941자 → **청킹 불필요**)
  - RAG용 본문 컬럼 `document_text` 생성 (`[궁이름] 유산명 - 설명글` 형식)
- [x] **벡터 DB 스키마** (`db/schema.sql` v2) — 표 6개, `vector(768)` (호환 뷰는 제거)
- [x] **임베딩+저장 실행 완료** (`embed_and_store.py`, 429 대응·이어하기 포함) — 이후 검색 평가가 정상 동작함으로 확인
- [x] **PostgreSQL + pgvector 설치 완료** (Windows, Docker)
- [x] **왕릉·경희궁·궁궐 개요 수집 → 정리 → 임베딩** (`collect_royal_tombs.py` → `clean_royal_tombs.py` → `embed_and_store.py`): 24건(능역 18 + 경희궁지 1 + 개요 5), DB 151건 확인
- [x] **`heritage_alias` → `heritage` 합치기**: 코드·SQL 수정, 임시 PostgreSQL에서 시험, 사용자 DB 적용(결과 숫자 확인은 아직)
- [x] **조선왕조실록 수집·정리** (`collect_sillok.py`, `clean_sillok.py`): 정제본 6,070건 (DB 미반영)
- [x] **DB 구조 검토·설계**: 7표 검토, 3층 구조 설계안(`docs/db_design_3layer.md`), Notion "DB 스키마" 페이지 갱신(실제 DB 값)

### RAG 핵심
- [x] **질문 임베딩 + 검색** (`search_test.py`, `RETRIEVAL_QUERY`, 코사인 거리 `<=>`)
- [x] **답변 생성** (`answer_test.py`): 상위 5개 → 프롬프트 → LLM, 429/503 재시도(지수 백오프) + 예비 모델 자동 전환, 하루 한도(PerDay) 구분
- [x] **검색 평가** (`eval_search.py`, 15문항 → 2026-10-06 **29문항**, 최신 결과는 6장 3-2. 아래는 15문항 시절 기록): 정답이 전부 상위 3위 안, 1위 12/15, **MRR 0.88** (이름형 1.00 · 설명형 0.93 · 별칭형 0.67).
  약점은 본문에 없는 단어로 묻는 **별칭형 질문**("정문" ↔ 본문의 "남문").
- [x] **답변 평가** (`eval_answer.py`): 정답 있는 15문항 정답 출처 선택 15/15, 환각 테스트 6/6(전부 한 문장 거절, 출처 줄 없음).
  3.1/3.5 모두 동일. 기준선 결과: `data/eval/answer_eval_gemini-3.5-flash-lite.csv`, `..._gemini-3.1-flash-lite.csv`
- [x] **LLM 확정**: 기본 `gemini-3.5-flash-lite` / 예비 `gemini-3.1-flash-lite`

### 백엔드
- [x] **`backend/rag.py`**: 검색·프롬프트·LLM 호출·출처 파싱·오류 분류(`QuotaExceededError` 429 / `ServiceBusyError` 503 / `DatabaseError` 503 / `LlmError` 502)
- [x] **`backend/main.py`**: `POST /api/ask`, `GET /api/health`, CORS(기본 `localhost:5173`), 입력 검증(1~300자), 내부 오류 메시지 비노출
  - 응답: `{answer, model, sources:[{gung_name, name, similarity, img_url, excerpt, cited}]}` (`cited` = AI가 출처로 직접 적은 유산)
  - 가짜 Gemini/DB로 35개 시험 통과 + **실제 `uvicorn` 기동, `/api/health`(chunk_count), `/docs` 확인 완료(사용자 PC)**

### 프론트엔드
- [x] **React+TS(Vite) 최소 화면**: 질문 입력(300자 카운터, Enter 전송), 예시 질문 버튼(마지막은 환각 시험용 "경희궁은 언제 지어졌어?"), 답변 카드(모델 표시), 출처 카드(`cited`는 크게, 나머지 후보는 접어서), 로딩/에러 표시, 헤더에 서버 연결 상태("연결됨 · 자료 N건")
- [x] 검증: 빌드(`tsc -b && vite build`)·린트 통과, **사용자 PC에서 화면 정상 표시 확인**
- 주의: `strictPort`로 5173 고정 (백엔드 CORS가 5173만 허용). VM에서 `npm install`을 하면 Windows용 파일이 깨지므로 `npm install`은 항상 사용자 PC에서 실행

### 환경 정리
- [x] 폴더 구조를 `backend/` 중심으로 정리, `.gitignore` 신설(API 키 커밋 방지)
- [x] **첫 git 커밋 완료**, 원격은 `https://github.com/jiyeoncodes/heritage-rag-agent.git`(`origin`). 커밋 전 `.env`가 추적 대상에 없는지 확인함. **푸시는 로그인 정보가 필요해 사용자 PC에서 직접 실행**

---

## 6. 다음 단계 로드맵

### 바로 해야 할 것 (1단계 마무리)

1. ~~백엔드 실제 기동 확인~~ ✅ 완료
2. ~~React+TypeScript 프론트엔드 최소 화면~~ ✅ 완료
3. ~~경희궁 · 조선 왕릉 데이터 보강~~ ✅ 수집·정리·임베딩 완료 (DB 151건). **이제 남은 것은 평가 갱신**
   - 3-1. ✅ 검색 회귀 확인 (2026-10-06 실행): 기존 15문항 MRR 0.88 → **0.87**(1등 80% 유지, 3등 안 100% 유지). 바뀐 건 "종묘 정전" 질문 2등→3등 하나뿐 → **회귀 없음**
   - 3-2. ✅ 왕릉·경희궁·개요 평가 질문 14개 반영 (`eval_search.py` **29문항**): 신규 14문항 MRR 0.91, 전체 **MRR 0.89 · 1등 83% · 3등 안 97%** (이름형 1.00 · 설명형 0.89 · 별칭형 0.73)
   - 3-3. ✅ 환각 테스트 7문항으로 교체 (`eval_answer.py halluc`, gemini-3.5-flash-lite): **7/7 전부 "제공된 자료에서는 확인할 수 없습니다." 거절** (광해군의 무덤도 지어내지 않음). ※ 결과 CSV 맨 아래 옛 질문 2줄(경희궁·영릉)은 옛 목록의 잔재라 무시
   - 3-4. ✅ 화면 예시 질문 교체 (`QuestionForm.tsx`: 단종의 무덤 / 광해군의 무덤)
   - 3-5. 능역(18건) 단위 vs 릉별 청킹 결정: 3-6 결과를 보고 판단 (동구릉 한 건에 9기 이야기가 섞여 있음)
   - 3-6. **하이브리드 검색 (구현 완료 2026-10-06, 실제 평가는 아직)**: 약점은 인물 이름이 건물 이름과 겹치는 질문. "사도세자의 무덤은?" 정답 융릉과 건릉이 **4등**(1등 창경궁 문정전), "문정왕후의 무덤은?" 태릉과 강릉이 **2등**(1등 문정전), "경복궁의 정문은?" 광화문 3등(별칭형, 기존 약점). 구현: `backend/hybrid_search.py`(질문 분류 → 범위 안 후보 → 키워드 점수 → 점수 합치기. DB·API 없이 단독 실행 가능) + `rag.py`의 `search_debug()`. ① 규칙 분류("무덤·능·○릉" → 능역 / 궁 이름 → 그 궁 / 충돌·모름 → 전체) ② 범위 안 1등 유사도 < 0.60이면 전체로 되돌림 ③ 키워드 점수(후보의 30% 넘는 흔한 단어 제외, 희귀할수록 가중) ④ 최종 = 벡터 유사도 + 0.15×키워드(가중 합). 비교용으로 `rrf`·`vector`(예전 방식) 선택 가능
   - 3-6 실측 결과 (2026-10-06, 29문항, `data/eval/search_eval_<방식>.csv`): 벡터만 MRR **0.888**(1등 24) / 가중 합 0.887(1등 24) / **RRF 0.922(1등 26)**. 기존 15문항은 벡터 0.867 → 가중 합 0.816 · RRF 0.849로 **오히려 하락**, 신규 14문항은 0.911 → 0.964 · **1.000**. 가중 합 alpha 0.10과 0.15는 순위가 완전히 같음(키워드 점수가 벡터 차이보다 훨씬 커서 alpha 변화가 안 먹힘)
   - 고쳐진 질문: 사도세자 4→1등, 문정왕후 2→1등. **새로 밀린 질문**: 경복궁 정문 3→5등(1등 근정문), 창경궁 정문 3→5등(1등 문정문) — "정문"이라는 단어가 다른 문 설명에 들어 있어 키워드가 그쪽을 밀어 올림(별칭형 약점 악화). 가중 합에서는 "경복궁에서 왕비가 지내던 침전은?"(1→2, 개요가 1등), "세조가 묻힌 능은?"(1→2, 서오릉이 1등)도 밀림. 대응: "묻힌·무덤" 등 왕릉 의도어는 키워드에서 제외(2026-10-06 반영), `rag.py` 기본 방식을 rrf로 변경, `KW_LABELS`/`--kw tomb`로 "키워드를 왕릉 질문에만 적용" 비교 가능
   - ⚠ **평가 한계**: 29문항은 튜닝에도 같이 쓰는 문항이라 과적합 위험이 있음 → 새 문항을 따로 추가해 검증할 것. `eval_answer.py`/`answer_test.py`는 2026-10-06까지 **옛 벡터 검색을 쓰고 있었음**(환각 7/7은 하이브리드 이전 결과) → `answer_test.py`가 `rag.search`를 쓰도록 고치고 `eval_answer.py`에 `--fresh` 옵션 추가. 하이브리드 기준 환각 재평가는 아직. 또 `SYSTEM_INSTRUCTION`이 "궁궐과 종묘 해설사"로만 되어 있어 왕릉 반영 여부 점검 필요
   - **3차 실측 (2026-10-06, RRF + 키워드를 왕릉 질문에만 적용 = 현재 기본값)**: 29문항 **MRR 0.93 · 1등 26/29 · 3등 안 29/29** (벡터만 0.888 · 24 · 28). **기준선보다 나빠진 질문 0개**, 좋아진 질문: 사도세자 4→1, 문정왕후 2→1. 남은 3등 3개는 경복궁 정문·창경궁 정문(별칭형)·종묘 정전(기준선과 동일). 키워드를 모든 질문에 적용하면 MRR 0.92·3등 안 27/29(정문 2개가 5등)이라 `hybrid_search.KW_LABELS = {"왕릉"}`을 기본값으로 확정(`--kw all`로 비교 가능). 결과 파일: `search_eval_rrf.csv`(기본), `search_eval_rrf_kwall.csv`, `search_eval_vector.csv`, `search_eval_weighted*.csv`
   - 환각 재평가(하이브리드 기준, `eval_answer.py halluc --fresh`): **7/7 거절**. 단 "창덕궁 주차장" 답변 끝에 "출처: [창덕궁] 주차장 정보 없음"이 붙음(프롬프트 규칙 6은 출처 줄 금지) — 자동 판정은 거절로 잡았지만 형식 위반 1건. 프롬프트가 왕릉을 반영하지 않은 문제와 함께 점검 필요
   - **프롬프트 수정 (2026-10-06, `rag.py`·`scripts/answer_test.py` 두 곳 동일)**: ① 해설사 범위에 경희궁·조선왕릉 추가 ② 출처 형식을 `[분류 유산명]`으로 일반화하고 예시(`[조선왕릉 영월 장릉]`) 추가 ③ 규칙 6에 "거절 문장 뒤에 아무 글도 붙이지 말 것" 추가 ④ 규칙 7 신설: 능역 자료에서 인물의 무덤이 명시된 경우에만 답하고 인물이 언급만 되면 거절(광해군 시험용). **이 수정 이후의 답변 평가는 아직 실행 전** — 규칙 7이 정답 있는 왕릉 질문까지 과하게 거절하는지(과잉 거절) 확인 필요. 이전 결과는 `data/eval/answer_eval_gemini-3.5-flash-lite_before_hybrid_20261006.csv`로 보관
   - **답변 평가 실측 (2026-10-06, 프롬프트 수정 후, `answer_eval_gemini-3.5-flash-lite.csv` 36번)**: 정답 있는 29문항 **검색 적중 29/29 · 정답 이름이 답변에 등장 29/29 · 과잉 거절 0건**(규칙 7이 정답 질문을 막지 않음). 환각 **7/7 거절**. 단 자동 점수의 "출처 정답"은 3/29로 급락 — **답이 틀린 게 아니라 출처 형식이 `[창덕궁] 돈화문`(대괄호 분리)으로 바뀐 탓**(프롬프트 규칙 4를 "[분류 유산명]"으로 쓴 부작용). 이건 서비스에서도 `cited` 표시가 깨지는 실제 문제였음 → 규칙 4에 "대괄호 하나 / 틀린 예" 명시, `rag.split_answer_and_citations()`가 대괄호를 나눠 써도·문장 끝 "출처:"도 읽도록 보강, `eval_answer.py`의 출처 판정도 대괄호 무시. **환각 답변 3건(놀이공원·가장 큰 능·동구릉 주차장)이 거절 뒤에 출처를 붙임(규칙 6 위반 3/7)** → 코드에서 거절 답변의 출처를 제거하도록 보호장치 추가(프롬프트만으로는 불안정)
   - **발견된 답변 품질 문제**: "세종대왕릉(영릉)은?"이 "영릉(寧陵) 동쪽에 위치"라고 답함 — 자료의 능역 청크에 세종의 영릉(英陵)과 효종의 영릉(寧陵)이 함께 있어 LLM이 섞음(효종릉이 세종릉 동쪽으로 옮겨 온 것). 능역 단위 청크의 한계 → 6장 3-5(릉별 청킹) 판단 근거
   - **3-8. 임베딩 입력에서 머리말 제거 (2026-10-06 결정·코드 반영, DB 재임베딩은 사용자 PC에서 실행 전)**: 지금까지는 `[경복궁] 신무문 - 설명글`(머리말 포함)을 통째로 임베딩했음 → 같은 분류의 글에 같은 머리말이 반복돼 벡터가 서로 가까워지는 부작용 우려. 이제 `heritage_chunk.chunk_text`에는 **설명글 원문만** 저장·임베딩하고, 머리말 `[분류] 유산명 - `은 `heritage.group_name`·`name_kor`(이미 있는 컬럼)에서 **LLM에게 줄 때 `rag.build_prompt()`가 붙임**(출처 표기용 머리말은 그대로). `embed_and_store.py`는 `add_chunk_text()`로 머리말을 떼고(머리말이 예상과 다르면 멈춤), 궁궐 데이터도 본문이 바뀌면 update(전부 재임베딩). 검증: CSV 151건 머리말 round-trip 불일치 0건, 궁궐 127건 본문 == `explanation_kor`, 임시 DB에서 151 insert → 옛 상태(머리말 포함) 재현 → 151 update → 재실행 전부 skip, 저장된 벡터가 "원문의 벡터"와 일치. **효과(검색 점수)는 미측정** → 재임베딩 후 `eval_search.py`(질문 벡터 캐시는 그대로 유효)로 이전 결과와 비교해 나빠지면 되돌림 가능(백업·비교 파일 보관)
   - 재임베딩 실행: `docker exec -i postgres psql -U postgres -v ON_ERROR_STOP=1 < db\schema.sql`(주석만 바뀜) → `python scripts\embed_and_store.py`(151건 update, 임베딩 약 151번) → `python scripts\eval_search.py` · `--method vector`로 비교
   - 남은 일: ⓐ 재임베딩 + 검색 재평가 ⓑ 수정 후 답변 재평가 `python scripts\eval_answer.py halluc --fresh` + `answerable --fresh`(출처 점수 복구·환각 출처 제거 확인, LLM 36번) ⓒ 새 검증용 질문 10개 추가(과적합 확인) ⓓ 3-5 릉별 청킹 결정 ⓔ 커밋
   - 3-7. 현재 DB 사실(2026-10-06 확인): "사도세자"는 12개 청크에 나오고 "문정왕후"는 2개(선릉과 정릉·태릉과 강릉)에만 나옴 → 키워드만으로는 사도세자 질문이 안 풀릴 수 있어 질문 의도(능역) 가중이 필요
4. ✅ 평가 질문 29문항으로 확대 완료 (이전 설명: 3-2 초안이 반영되면 29문항) (현재 15문항은 적어서 한두 개로 점수가 출렁이고, 자동 점수는 이미 만점이라 **변별력이 없음**)
5. `rag.py`와 `scripts/answer_test.py`의 프롬프트·재시도 코드 중복 정리
6. ~~첫 git 커밋~~ ✅ 로컬 커밋 완료 (GitHub 푸시는 사용자 PC에서 `git push -u origin main`). **푸시 전 주의**: `backend/data/raw/sillok_xml/`(약 961MB)는 `.gitignore`에 추가해 둠. `sillok_heritage_articles.jsonl`(약 46MB) 등 큰 데이터 파일도 커밋할지 확인 후 `git add` (`git add .`로 한꺼번에 올리지 말 것)

### 이후 단계 (확장)

- **2단계 Agent**: 질문 유형에 따라 DB 조회 / 문헌 검색 / 관계 검색 중 도구를 선택하도록 확장 (이때 LangChain/LangGraph 검토). 정제된 실록 6,070건은 이때 "문헌 검색 도구"로 붙이는 것이 자연스러움 (한문 처리 방침은 3장)
- **3단계 관계 탐색**: 실록ㆍ한국사데이터베이스 등에서 인물ㆍ사건ㆍ지역 데이터를 추가해 유산과 연결. 사건 노드 후보로 기상청 기상기록(재해), 인물 노드는 별도 인물 API(미정) — 3장 "추가로 모은 데이터" 참고
- **4단계 멀티모달**: 수집된 이미지(`img_url`)를 활용한 이미지 기반 검색 (API 응답에 `img_url`은 이미 포함)
- **배포**: 로컬 검증이 끝난 뒤 GCP `e2-micro` 무료 인스턴스에 백엔드+DB 배포 (이때 `backend/`만 올리면 되도록 구성함)

---

## 7. 이 프로젝트에서 AI(Claude)가 따라야 할 원칙

이 프로젝트의 사용자는 **AI 엔지니어 학습자**이며, 정답만 받는 것이 아니라 **원리를 이해하며
성장하는 것**을 목표로 함. 코드나 설명을 제공할 때 아래 원칙을 지킬 것:

- 파이썬 코드에는 **상세한 한글 주석**을 포함하고, 파일 상단에 파일명을 주석으로 표시함
- 코드만 주지 않고, **동작 과정을 함께 설명**함
- 어려운 개념은 쉬운 말로 풀어서 설명하고, 전문 용어를 그대로 쓰지 않음
- 오류가 발생하면 **① 원인 → ② 해결 방법 → ③ 수정된 코드** 순서로 설명함
- 비교가 필요하면 표로 정리하고, 설명 끝에는 핵심 개념을 짧게 요약함
- 장황하거나 추상적인 설명은 지양함
- **실행 가능한 부분은 직접 검증**하고(로컬 CSV 처리, 가짜 부품으로 하는 로직 시험 등), 외부 API·DB 등 접근 불가능한
  부분은 "검증하지 못했다"고 명확히 밝힌 뒤 코드를 제공함
- 데이터를 다룰 때는 **원본(raw)을 항상 보존**하고, 정리된 결과는 별도 파일로 저장함
- **사용자 환경은 Windows + 명령 프롬프트(cmd) + venv**임. 명령은 cmd 기준으로 안내할 것 (`set 변수=값`, `echo %변수%`).
  PowerShell 문법(`$env:...`, `Remove-Item`)은 동작하지 않음. 스크립트는 `backend/`에서 `python scripts\파일명.py`로 실행
  (`scripts` 안으로 `cd` 하면 Windows가 폴더를 잠가 폴더 이동·삭제가 막힐 수 있음)
- **무료 티어 한도를 고려해 호출 수를 설계**하고, 평가 스크립트는 이어하기·질문별 저장을 유지함
- **평가 결과를 해석할 때는 원문과 대조**함. 자동 점수는 이미 만점이라 차이를 못 가리고, 답변의 근거가 정답 문서가 아니라
  **함께 검색된 다른 문서**에 있을 수 있음 (예: 창경궁 "정문"은 홍화문 문서가 아니라 선인문 문서에 적혀 있음). 검색된 5개 문서를 모두 확인한 뒤 환각이라고 판단할 것
- 비밀 정보(`.env`의 API 키)는 출력·커밋하지 않음. 설정 확인이 필요하면 변수 이름이나 비밀이 아닌 값만 확인함
- **DB 접근 한계**: Claude의 작업 환경에서는 사용자 PC의 DB(Docker)에 접속할 수 없음. DB 상태는 `backend/db/inspect_samples.sql`을 사용자가 실행해 결과를 붙여 주는 방식으로 확인하고, 확인하지 못한 값은 "형식 예시" 또는 "미확인"으로 구분해서 적을 것. SQL을 바꿀 때는 임시 PostgreSQL에서라도 먼저 시험하되, 사용자 DB에 적용한 결과는 미확인으로 둠
- 용어는 **"청크"**로 통일 ("덩어리" 사용 금지)

---

## 8. 빠른 참조

**환경변수 (`backend/.env`, 템플릿은 `backend/env.example`)**
```
GEMINI_API_KEY=...
DB_HOST=localhost
DB_PORT=5432
DB_NAME=postgres        # 이 DB에 v2 표(heritage 등)가 있음 (docker-compose의 POSTGRES_DB=rfp_rag 는 초기 생성 DB 이름일 뿐 사용 안 함)
DB_USER=postgres
DB_PASSWORD=postgres
LLM_MODEL=gemini-3.5-flash-lite
# 선택: LLM_FALLBACK_MODEL=gemini-3.1-flash-lite
# 선택: CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

**가상환경 만들기 / 라이브러리 설치 (cmd)**
```bat
cd C:\project\heritage-rag-agent\backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```
(파이썬 3.10과 3.13이 둘 다 설치된 흔적이 있음 → `python --version`으로 venv가 쓰는 버전 확인)

**PostgreSQL(Docker)**
```bat
cd C:\project\heritage-rag-agent\docker
docker compose up -d                                    :: DB 기동
docker ps                                               :: 컨테이너 `postgres` 실행 중인지 확인
docker exec -it postgres psql -U postgres               :: DB 직접 접속 (SELECT COUNT(*) FROM heritage_chunk;)
docker exec -i postgres psql -U postgres < ..\backend\db\schema.sql    :: 스키마 적용 (여러 번 실행해도 안전)
docker exec -i postgres psql -U postgres -v ON_ERROR_STOP=1 < ..\backend\db\migrate_alias_to_heritage.sql   :: 별칭 표 합치기 (이미 합친 DB에서 다시 실행해도 안전)
docker exec -i postgres psql -U postgres < ..\backend\db\inspect_samples.sql > ..\backend\db\inspect_result.txt   :: DB 내용 점검 (읽기만 함)
```

**스크립트 실행 순서 (모두 `backend/`에서)**
```bat
cd C:\project\heritage-rag-agent\backend
venv\Scripts\activate
python scripts\collect_gung_list.py     :: → data\raw\heritage_gung_list.csv
python scripts\collect_gung_detail.py   :: → data\raw\heritage_gung_detail.csv
python scripts\clean_gung_detail.py     :: → data\processed\heritage_gung_detail_clean.csv
python scripts\collect_royal_tombs.py   :: → data\raw\heritage_royal_tombs_detail.csv (왕릉 18 + 경희궁지 1 + 개요 5)
python scripts\clean_royal_tombs.py     :: → data\processed\heritage_royal_tombs_clean.csv
python scripts\embed_and_store.py       :: → PostgreSQL v2 표(heritage 등). 두 CSV(궁궐·왕릉)를 모두 처리, 이어하기 지원 (--source gung|royal 로 하나만 가능)
python scripts\collect_sillok.py        :: 실록 XML(data\raw\sillok_xml\) → data\raw\sillok_heritage_articles.csv/.jsonl (DB에는 안 들어감)
python scripts\clean_sillok.py          :: → data\processed\sillok_heritage_articles_clean.csv (6,070건, DB 미반영)
```

**검색·답변 시험과 평가 (`backend/`에서)**
```bat
python scripts\search_test.py "경복궁의 정문은 어디야?"   :: 검색만 (LLM 호출 없음)
python scripts\answer_test.py "경복궁의 정문은 어디야?"   :: 검색 + LLM 답변 (LLM 1회 호출)
python scripts\eval_search.py                              :: 검색 평가 15문항 (LLM 호출 없음, 무료)
python scripts\eval_answer.py halluc                       :: 환각 테스트만 (LLM 6회)
python scripts\eval_answer.py                              :: 전체 21문항 (LLM 21회, 하루 한도에 걸리면 저장 후 멈추고 다시 실행하면 이어서 함)
```
실행 첫 줄의 `모델: ...`이 `.env`의 `LLM_MODEL`과 같은지 확인할 것. 데이터·프롬프트를 바꾸기 전에 `data\eval\` 결과를 날짜를 붙여 복사해 두면 기준선이 됨.

**백엔드 서버 실행 (`backend/`에서)**
```bat
uvicorn main:app --reload --port 8000
```
- 시험 화면: http://localhost:8000/docs
- 상태 확인: http://localhost:8000/api/health  (`chunk_count`가 저장된 유산 수)
- 질문: `POST /api/ask` `{"question": "경복궁의 정문은 어디야?"}`

**프론트엔드 실행 (cmd, 터미널 2개)**
```bat
:: 터미널 1 - 백엔드
cd C:\project\heritage-rag-agent\backend
venv\Scripts\activate
uvicorn main:app --reload --port 8000

:: 터미널 2 - 프론트엔드 (처음 한 번만 npm install)
cd C:\project\heritage-rag-agent\frontend
npm install
npm run dev        :: http://localhost:5173
npm run build      :: 타입 검사 + 빌드
npm run lint
```
