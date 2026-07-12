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
- [ ] 업로드 파일 크기·타입 검증이 있는가. (현재 `/api/predict`에 없습니다.)
- [ ] 추론 결과를 `Prediction(label, score)`로 정규화해서 반환하는가.
- [ ] 모델 실험 코드가 제품 코드와 같은 커밋에 섞이지 않았는가.
- [ ] `runs/`에 새 `.pt` 파일을 추가하지 않았는가. 이미 70MB입니다.

### 로깅

- [ ] `setup_level_logger(logging.INFO)`로 만든 로거에 `.error()`를 호출하지 않았는가. `LevelFilter` 때문에 **아무 데도 기록되지 않습니다.**
- [ ] `print()`를 쓰지 않았는가.

### 테스트

- [ ] <!-- TODO: 확인 필요 - 테스트 프레임워크 미도입. 도입 전까지는 수동 검증 결과를 PR 본문에 기록합니다. -->

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
