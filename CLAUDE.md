# heritage-rag-agent 프로젝트 가이드

> 이 문서는 이 프로젝트에 대해 작업할 때(특히 Claude Code 등 AI 도구를 쓸 때) 읽는
> 배경 지식 문서입니다. 프로젝트 루트(`C:\project\heritage-rag-agent`)에 두세요.
> 마지막 갱신: 2026-10-03

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

**현재 위치 (2026-10-03)**: 1단계의 **질문 단계(검색 → LLM 답변 → 출처 표시)가 화면까지 end-to-end로 동작**함
(백엔드 `rag.py`/`main.py` 실제 기동 확인, React+TS 프론트 화면 정상 확인).
**1단계에서 남은 것은 데이터 범위 보강(경희궁 · 조선 왕릉 40기)** 이며, 이것이 끝나야 1단계 완료.

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

### ⚠️ 알려진 데이터 공백 (출처 탐색 완료, 수집은 아직)

| 항목 | 상태 |
|---|---|
| **경희궁** | 궁궐 API에는 없음 → **국가유산청 '국가유산 종합 Open API'에 `경희궁지`(사적 제271호)로 있음** (아래 참고) |
| **조선 왕릉 40기** | 같은 종합 API에 **사적 "능역" 18건**으로 등록됨 (아래 참고). 수집 시작 전 |

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

다음 단계 후보: `collect_royal_tombs.py`(목록 → 조선왕릉 18건 + 경희궁지 필터 → 상세 수집 → `data/raw`에 저장) → 정리 → `embed_and_store.py` → `eval_search.py`(회귀 확인).

이전에 언급된 다른 보강 후보: 국가유산청 문화재 공간정보(WFS), 국사편찬위원회 한국사데이터베이스, 조선왕조실록, 우리역사넷.
(데이터를 넣기 전까지 경희궁·왕릉 질문은 평가의 "환각 테스트"에서 "확인할 수 없다"고 답해야 정상. 데이터를 넣으면 평가 기대값도 바꿔야 함.)

---

## 4. 폴더 구조 (2026-10-03 정리 완료)

Python 관련 파일은 모두 `backend/` 안에 있고, `.env`(API 키)도 `backend/`에만 둠. 프론트엔드는 키를 갖지 않음.

```
heritage-rag-agent\
├── backend\
│   ├── main.py             # FastAPI 서버 (POST /api/ask, GET /api/health)
│   ├── rag.py              # 검색 + LLM 답변 + 출처 정리 + 오류 분류
│   ├── requirements.txt
│   ├── .env                # 실제 키 (git 제외)
│   ├── env.example         # .env 템플릿 (이름에 점 없음, git 포함)
│   ├── venv\               # 가상환경 (git 제외)
│   ├── db\
│   │   └── schema.sql      # pgvector 테이블 정의
│   ├── data\
│   │   ├── raw\            # 수집 원본 CSV (목록조회, 상세조회) — 항상 보존
│   │   ├── processed\      # 정리 완료 CSV (RAG 문서로 바로 사용)
│   │   └── eval\           # 평가 결과 CSV (기준선 비교용으로 보관)
│   └── scripts\            # 데이터 수집ㆍ정리ㆍ임베딩ㆍ검색ㆍ평가 스크립트
│       ├── collect_gung_list.py
│       ├── collect_gung_detail.py
│       ├── clean_gung_detail.py
│       ├── embed_and_store.py
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
- [x] **벡터 DB 스키마** (`db/schema.sql`) — `heritage_chunks` 테이블, `vector(768)`
- [x] **임베딩+저장 실행 완료** (`embed_and_store.py`, 429 대응·이어하기 포함) — 이후 검색 평가가 정상 동작함으로 확인
- [x] **PostgreSQL + pgvector 설치 완료** (Windows, Docker)

### RAG 핵심
- [x] **질문 임베딩 + 검색** (`search_test.py`, `RETRIEVAL_QUERY`, 코사인 거리 `<=>`)
- [x] **답변 생성** (`answer_test.py`): 상위 5개 → 프롬프트 → LLM, 429/503 재시도(지수 백오프) + 예비 모델 자동 전환, 하루 한도(PerDay) 구분
- [x] **검색 평가** (`eval_search.py`, 15문항): 정답이 전부 상위 3위 안, 1위 12/15, **MRR 0.88** (이름형 1.00 · 설명형 0.93 · 별칭형 0.67).
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
3. **경희궁 · 조선 왕릉 데이터 보강 (← 지금 해야 할 일, 1단계 완료 조건)** — 출처는 찾음(3장 참고), 수집 스크립트 작성부터
   - 보강 후: `embed_and_store.py` → `eval_search.py`(무료)로 검색이 무너지지 않았는지 먼저 확인 → `eval_answer.py`
   - 평가 질문도 같이 추가하고(왕릉 질문 5~10개), 기존 질문은 그대로 두어 **성능 유지 여부(회귀)** 확인. 환각 테스트의 경희궁·왕릉 문항은 기대값을 바꿔야 함
4. 평가 질문 20~30개로 확대 (현재 15문항은 적어서 한두 개로 점수가 출렁이고, 자동 점수는 이미 만점이라 **변별력이 없음**)
5. `rag.py`와 `scripts/answer_test.py`의 프롬프트·재시도 코드 중복 정리
6. ~~첫 git 커밋~~ ✅ 로컬 커밋 완료 (GitHub 푸시는 사용자 PC에서 `git push -u origin main`)

### 이후 단계 (확장)

- **2단계 Agent**: 질문 유형에 따라 DB 조회 / 문헌 검색 / 관계 검색 중 도구를 선택하도록 확장 (이때 LangChain/LangGraph 검토)
- **3단계 관계 탐색**: 실록ㆍ한국사데이터베이스 등에서 인물ㆍ사건ㆍ지역 데이터를 추가해 유산과 연결
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

---

## 8. 빠른 참조

**환경변수 (`backend/.env`, 템플릿은 `backend/env.example`)**
```
GEMINI_API_KEY=...
DB_HOST=localhost
DB_PORT=5432
DB_NAME=postgres        # 이 DB에 heritage_chunks 테이블이 있음 (docker-compose의 POSTGRES_DB=rfp_rag 는 초기 생성 DB 이름일 뿐 사용 안 함)
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
docker exec -it postgres psql -U postgres               :: DB 직접 접속 (SELECT COUNT(*) FROM heritage_chunks;)
docker exec -i postgres psql -U postgres < ..\backend\db\schema.sql    :: 스키마 적용 (처음 한 번)
```

**스크립트 실행 순서 (모두 `backend/`에서)**
```bat
cd C:\project\heritage-rag-agent\backend
venv\Scripts\activate
python scripts\collect_gung_list.py     :: → data\raw\heritage_gung_list.csv
python scripts\collect_gung_detail.py   :: → data\raw\heritage_gung_detail.csv
python scripts\clean_gung_detail.py     :: → data\processed\heritage_gung_detail_clean.csv
python scripts\embed_and_store.py       :: → PostgreSQL heritage_chunks 테이블 (이어하기 지원)
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
