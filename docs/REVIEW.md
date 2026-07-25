# REVIEW

## 머지 전 필수 통과 조건

자동화된 테스트·린트가 없으므로 **수동 검증이 유일한 게이트**입니다. 아래를 실제로 실행한 뒤 결과를 PR에 남깁니다.

```bash
docker compose up -d postgres
source venv/bin/activate
pip install -r requirements.txt

# 반드시 저장소 루트에서 (YOLO 가중치가 상대경로)
uvicorn main:app --port 8000

# 스키마 확인
curl -sf http://127.0.0.1:8000/openapi.json | python3 -m json.tool | head

# 앱이 쓰는 계약 3종 (predict·gpt-predict 는 Bearer 필수 — 무토큰이면 401)
curl -X POST http://127.0.0.1:8000/api/predict \
  -H "Authorization: Bearer <세션토큰>" -F "file=@<음식사진>.jpg"
curl -X POST http://127.0.0.1:8000/api/gpt-predict \
  -H "Authorization: Bearer <세션토큰>" \
  -H 'Content-Type: application/json' -d '{"text":"김치찌개 1인분 칼로리","max_tokens":256}'
curl -X POST http://127.0.0.1:8000/api/auth/signup/request-code \
  -H 'Content-Type: application/json' -d '{"phone_number":"010-1234-5678"}'
```

또는 워크스페이스 실행기: `../dev.sh server`

| 조건 | 확인 방법 |
|------|-----------|
| 서버가 예외 없이 기동한다 | `uvicorn main:app` (HF_TOKEN 없으면 import 단계에서 죽습니다) |
| OpenAPI 스키마가 생성된다 | `/openapi.json` 200 |
| 변경/추가한 엔드포인트가 **성공·실패 케이스 모두** 의도한 응답을 준다 | `curl` |
| API 계약을 바꿨다면 `k-calAI-RN`을 함께 수정했다 | 두 저장소 diff |
| `.env.example`이 새 환경변수를 포함한다 | diff |
| 비밀값이 커밋에 없다 | `git diff --staged` |
| `runs/`에 새 가중치를 추가하지 않았다 | `git diff --staged --stat -- runs` |

## 리뷰 체크리스트

### Correctness

- [ ] `commit()`이 서비스 최상위 진입점에서만 호출되는가. 내부 헬퍼는 `flush()`까지인가.
- [ ] `datetime`이 timezone-aware UTC인가. `datetime.utcnow()`를 쓰지 않았는가.
- [ ] `expires_at > now`, `consumed_at.is_(None)` 같은 유효성 조건이 쿼리에 포함되어 있는가.
- [ ] 휴대폰 번호가 저장·조회 양쪽에서 `normalize_phone_number`를 거치는가.
- [ ] `select()` + `db.scalar()`를 썼는가. `db.query()` 레거시가 아닌가.
- [ ] DB 스키마를 바꿨다면, `create_all`이 **기존 테이블의 컬럼 변경을 반영하지 않는다**는 점을 고려했는가.
- [ ] 모델 가중치 경로를 바꿨다면 `services/predict_service.py` 한 곳만 고쳤는가.
- [ ] 새 import가 **모듈 로드 시점에 네트워크·파일·환경변수를 건드리지** 않는가.

### API 계약

- [ ] 새 라우트가 `include_router(..., prefix="/api")`를 경유하는가.
- [ ] `response_model`과 `responses={...}`가 지정되어 있는가.
- [ ] **실패 시 `return`이 아니라 `raise HTTPException`을 쓰는가.** `response_model`이 걸린 라우트에서 다른 형태를 `return`하면 500 평문이 나갑니다.
- [ ] 실패 응답이 `{"detail": "..."}` 형태인가. 앱의 `readErrorMessage`가 `detail`만 파싱합니다.
- [ ] 응답에 ORM 객체나 라이브러리 내부 타입이 새어나가지 않는가.
- [ ] 경로·요청 필드·응답 필드 변경이 `k-calAI-RN/services/*.ts`와 일치하는가.

### 레이어

- [ ] `api/`에 비즈니스 로직, SQLAlchemy 쿼리, `os.getenv`가 없는가.
- [ ] `services/`가 `fastapi`를 import 하지 않는가.
- [ ] `schemas/`가 `models/`나 `services/`에 의존하지 않는가.

### 보안

- [ ] **`AUTH_INCLUDE_DEV_CODE`가 운영에서 `false`인가.** 기본값이 `true`입니다.
- [ ] **`AUTH_CODE_PEPPER`가 기본값(`development-only-pepper`)이 아닌가.**
- [ ] 인증번호·세션 토큰·`HF_TOKEN`이 로그에 남지 않는가.
- [ ] 예외 메시지에 스택트레이스·라이브러리명·SQL이 포함되지 않는가.
- [ ] `CORS_ALLOW_ORIGINS`가 운영 환경에서 와일드카드가 아닌가. `allow_origin_regex`가 localhost를 허용하고 `allow_credentials=True`입니다.
- [ ] 새 비밀값이 `.env.example`에 **빈 값**으로만 들어갔는가.
- [ ] 새 엔드포인트가 인증 없이 공개되어도 되는가. (무인증 공개는 Auth 가입·로그인 4종뿐입니다. 2026-07-12부터 `/api/predict`·`/api/gpt-predict`도 Bearer 필수, `/api/s3/*`는 제거됨.)

### 추론·모델

- [ ] 모델 로딩 위치를 바꿨다면 서버 시작 시간, 첫 요청 지연, **cwd 의존성**을 확인했는가.
- [ ] 업로드 파일 크기·타입 검증을 거치는가. `/api/predict`는 `services/upload_validation.py`로 크기(413)·content-type(415)·디코드 가능성(400)을 확인한다. 입력 검증(4xx)은 라우트 `try` **밖**에 둬서 500으로 뭉개지지 않게 한다.
- [ ] 추론 결과를 `Prediction(label, score)`로 정규화해서 반환하는가.
- [ ] 모델 실험 코드가 제품 코드와 같은 커밋에 섞이지 않았는가.
- [ ] `runs/`에 새 `.pt` 파일을 추가하지 않았는가. 이미 70MB입니다.

### 로깅

- [ ] `setup_level_logger(logging.INFO)`로 만든 로거에 `.error()`를 호출하지 않았는가. `LevelFilter` 때문에 **아무 데도 기록되지 않습니다.**
- [ ] `print()`를 쓰지 않았는가.

### 테스트

- [ ] 인증·인가 등 로직 변경은 `tests/`에 회귀 테스트를 추가했는가. (`venv/bin/python -m pytest`로 전부 통과)
- [ ] 서비스 함수를 바꿨다면 계약(성공/예외/경계)을 테스트로 고정했는가.
- [ ] 테스트가 없는 부분(API 레이어, 추론 파이프라인 등)은 수동 검증 결과를 PR 본문에 기록했는가.

> pytest는 서비스 레이어 + API 레이어(TestClient)를 커버한다. `api/__init__.py`를 비워(2026-07-12) auth 등 라우터를 torch 없이 올릴 수 있다 — `tests/test_auth_api.py`. predict 계열은 `predict_image`를 목으로 대체하면 API 테스트 가능.

## 공유 상수를 건드릴 때 (2026-07-25 신설)

여러 모듈이 나눠 쓰는 상수는 **한쪽만 고쳐도 아무도 안 터지고 조용히 틀린다.** 하루에 같은
종류의 사고가 세 번 났고, 전부 예외 없이 잘못된 값이 화면까지 나갔다:

1. 경고 축(`WARNING_AXES`)에 당류를 더했더니 그 목록을 참조하던 하루 누적이 함께 깨졌다 —
   합계는 늘 0, 참고치는 기본값으로 떨어져 **없는 의학 기준**("당류 투석 시 참고치 1,000 mg")이
   표시됐다.
2. 당뇨의 `dietary_tags`에 `low_sodium`이 없어 **나트륨 축이 한 번도 돌지 않았다.**
3. 질병에 축이 붙으면 `exclude_keywords` 경로를 타지 않는데, 그 키워드를 축이 흡수하지 않아
   기존 경고가 사라질 뻔했다.

### 규약

- **소비처가 요구하는 조건이 다르면 목록을 분리한다.** 경고 축과 하루 누적 축은 이제 별개다 —
  경고는 "무엇을 먹었나", 누적은 "얼마나 먹었나"라 요구하는 근거 수준이 다르다.
- **이름을 조립해 컬럼을 찾지 않는다.** `getattr(row, f"{nutrient}_mg")`는 컬럼이 없어도
  `None`이 되어 조용히 0으로 집계된다. 명시적 매핑을 쓰고 모르는 키는 `KeyError`로 터뜨린다.
- **의학 수치를 기본값으로 흘리지 않는다.** "칼륨이 아니면 인" 같은 분기는 새 축이 들어오는
  순간 엉뚱한 기준을 만든다. 아는 것에만 값을 주고 나머지는 `None`.
- **코드에 축을 선언해도 DB 태그가 없으면 돌지 않는다.** 축·질환·병기를 늘릴 때는 시드나
  마이그레이션까지 함께 본다.

### 강제 수단

`tests/test_shared_constant_integrity.py`가 위 넷을 전부 깨뜨린다. 문서만 믿지 않는다 —
사고 재현으로 검증했고, 축을 되돌리거나 키워드 흡수를 빼면 실제로 빨간불이 켜진다.

## 리뷰 시 흔한 실수

| 실수 | 왜 문제인가 |
|------|-------------|
| `response_model`이 걸린 라우트에서 실패를 `return` | 검증에 걸려 **500 평문 `Internal Server Error`**가 나갑니다. `raise HTTPException(...)`을 쓰세요 |
| `info_logger.error()` 호출 | INFO 로거의 `LevelFilter`가 ERROR 레코드를 버려 **어디에도 남지 않습니다.** `error_logger`를 따로 만드세요 |
| `HF_TOKEN`을 셸에 export했으니 `.env`는 필요 없다고 가정 | 반대도 성립합니다. **둘 중 하나만 있으면 됩니다.** 다만 `load_dotenv()`가 cwd에서 `.env`를 찾으므로 실행 위치에 따라 결과가 달라집니다 |
| 아무 디렉토리에서 `uvicorn main:app` 실행 | YOLO 가중치와 `.env` 탐색이 모두 **cwd 상대**입니다 |
| `create_all`이 컬럼 변경을 반영한다고 가정 | 신규 테이블만 만듭니다 |
| 세션 토큰이 검증되고 있다고 가정 | 발급만 하고 검증·폐기 코드가 없습니다 |
| `/api/predict`, `/api/gpt-predict`가 무인증 공개라고 가정 | 2026-07-12부터 Bearer 필수입니다. `/api/s3/*`는 같은 날 제거됐습니다 |
| `transformers`가 추론에 쓰인다고 가정 | 전부 주석 처리된 잔재입니다. 실제 분류는 ultralytics YOLO |
| 함수명 `answerByGptOss20B`를 보고 20B 모델이라 가정 | 실제 호출 모델은 `openai/gpt-oss-120b` (provider `groq`) |
| `master`에 push하면 배포된다고 가정 | 배포 트리거는 **`dev` 브랜치 push**입니다 |
| `dev`에 실험 커밋 push | **즉시 NCP 서버로 배포됩니다** |

## 커밋

- 커밋 메시지는 한국어 `<type>: <요약>` 형식입니다. 관찰된 타입: `feat`, `fix`, `chore`, `refactor`, `add`.
- 전역 `commit-msg` 훅이 **한국어가 없는 제목을 거부합니다** (`Merge `/`Revert ` 접두는 예외).
- 모델 성능 작업과 API 안정화 작업을 한 커밋에 섞지 않습니다.
- API 계약 변경 커밋은 `k-calAI-RN` 대응 커밋과 짝을 이룹니다.

## 브랜치

| 브랜치 | 주의 |
|--------|------|
| `master` | 기본 브랜치. 직접 커밋하지 말고 브랜치를 따서 PR |
| `dev` | **push = 배포.** 검증 끝난 것만 |
| `ck-local` | 로컬 작업 브랜치 |
