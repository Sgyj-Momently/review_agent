# review_agent

블로그 초안 Markdown을 받아 **결정론적 품질 검사**를 수행하고 최종 Markdown을 반환하는 FastAPI 에이전트.

---

## 역할 (파이프라인 위치)

```
draft_agent → style_agent → [review_agent] → spring_orchestrator (최종 저장)
```

- **소비**: `style_agent`(또는 `draft_agent`)가 만든 `styled_markdown`, 제외 사진 목록(`excluded_photos`), SEO 주력 검색어(`target_keywords`)
- **생산**: 검사 결과 목록(`checks[]`), 이슈 수(`issue_count`), 최종 Markdown(`final_markdown`)
- 기본 경로에서는 LLM을 호출하지 않는다. `REVIEW_ENABLE_LLM_POLISH=true`로 설정 시 Ollama로 교정 폴리싱을 추가로 수행한다.

---

## API

### `GET /health`

서비스 상태 확인.

**응답 예시**

```json
{ "status": "ok", "service": "review_agent" }
```

---

### `POST /api/v1/reviews`

Markdown 본문을 검사하고 최종 Markdown을 반환한다.

**요청 바디**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `project_id` | `string` | Y | 프로젝트 식별자 (최소 1자) |
| `styled_markdown` | `string` | Y | 검사 대상 Markdown 전문 |
| `target_keywords` | `string` | N | SEO 주력 검색어 (`,` `\n` `;` `/` `·` 구분) |
| `photos` | `object[]` | N | 참조 허용 사진 목록 |
| `excluded_photos` | `object[]` | N | 최종 본문에서 제외해야 할 사진 목록 (`file_name` 포함) |

**요청 예시**

```json
{
  "project_id": "trip-001",
  "styled_markdown": "# 제주 흑돼지 맛집 후기\n\n제주 흑돼지 맛집을 다녀왔다...",
  "target_keywords": "제주 흑돼지 맛집",
  "excluded_photos": [{ "file_name": "private.jpg" }]
}
```

**응답 바디**

| 필드 | 타입 | 설명 |
|------|------|------|
| `project_id` | `string` | 요청과 동일 |
| `review_status` | `string` | `"ok"` / `"ok_polished"` / `"needs_attention"` |
| `final_markdown` | `string` | 최종 Markdown (LLM 폴리싱 적용 가능) |
| `checks` | `object[]` | 개별 검사 결과 목록 |
| `issue_count` | `int` | 실패한 검사 수 |
| `review_polished` | `bool` | LLM 폴리싱 적용 여부 |

**checks 항목**

각 항목은 `{ "name": string, "status": "pass" | "fail", "message": string }` 형태.

| name | 설명 |
|------|------|
| `non_empty` | 본문이 비어 있지 않은지 확인 |
| `has_title` | Markdown H1 제목이 존재하는지 확인 |
| `has_body` | 본문 토큰이 최소 8개 이상인지 확인 |
| `excluded_photos_not_referenced` | 제외 사진 파일명이 본문에 포함되지 않는지 확인 |
| `no_generic_filler` | 템플릿성 대체 문구(예: "여행의 흐름을 자연스럽게 이어준다") 부재 확인 |
| `no_repetitive_plain_impressions` | "좋았다/인상적이었다/분위기가 좋았다" 3회 미만 반복 확인 |
| `seo_title_contains_keyword` | `target_keywords` 지정 시 제목에 검색어 포함 확인 |
| `seo_keyword_in_body` | `target_keywords` 지정 시 본문에 검색어 1회 이상 포함 확인 |
| `seo_no_keyword_stuffing` | `target_keywords` 지정 시 같은 검색어가 4회 이상이면서 본문 토큰의 15% 초과 여부 확인 |

**응답 예시**

```json
{
  "project_id": "trip-001",
  "review_status": "ok",
  "final_markdown": "# 제주 흑돼지 맛집 후기\n\n...",
  "checks": [
    { "name": "non_empty", "status": "pass", "message": "본문이 비어 있지 않습니다." },
    { "name": "has_title", "status": "pass", "message": "제목이 Markdown H1으로 존재합니다." }
  ],
  "issue_count": 0,
  "review_polished": false
}
```

---

## 실행

### 로컬 (uvicorn)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn src.api_server:app --reload --port 8500
```

- Swagger UI: `http://127.0.0.1:8500/docs`
- Health: `http://127.0.0.1:8500/health`

### Docker

```bash
docker build -t review_agent .
docker run -e OLLAMA_BASE_URL=http://host.docker.internal:11434 -p 8500:8500 review_agent
```

---

## 설정

| 이름 | 설명 | 기본값 |
|------|------|--------|
| `REVIEW_ENABLE_LLM_POLISH` | LLM 교정 폴리싱 활성화 (`1` / `true` / `yes` / `on`) | `false` |
| `REVIEW_MODEL` | 폴리싱에 사용할 Ollama 모델 | `qwen2.5:14b` |
| `OLLAMA_BASE_URL` | Ollama API 엔드포인트 | `http://localhost:11434` |
| `OLLAMA_TIMEOUT_SECONDS` | Ollama 요청 타임아웃 (초) | `180` |

LLM 폴리싱은 기본 검사를 모두 통과(`issue_count == 0`)한 경우에만 실행된다. 폴리싱 결과에서 중국어 비율이 20%를 초과하면 자동으로 원본 Markdown으로 폴백한다.

---

## 테스트

```bash
# 빠른 실행 (커버리지 없음)
python3 -m unittest discover -s tests -t .

# 표준 검증 (커버리지 85% 게이트 포함)
scripts/verify.sh
```

`PYTHON` 환경변수로 인터프리터를 지정할 수 있다.

```bash
PYTHON=/usr/bin/python3 scripts/verify.sh
```

---

## 구조

```
review_agent/
├── src/
│   ├── api_server.py  # FastAPI 앱, 요청/응답 모델, 라우터
│   └── reviewer.py    # 결정론적 검사 로직, LLM 폴리싱, SEO/품질 체크
├── tests/
│   └── test_review_agent.py  # 단위·API 통합 테스트
├── scripts/
│   └── verify.sh      # 커버리지 게이트 실행 스크립트
└── requirements.txt
```
