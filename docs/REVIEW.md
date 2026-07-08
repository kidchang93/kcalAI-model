# REVIEW

## 머지 전 필수 통과 조건

자동화된 테스트·린트가 없으므로 **수동 검증이 유일한 게이트**입니다. 아래를 실제로 실행한 뒤 결과를 PR에 남깁니다.

```bash
docker compose up -d postgres
source venv/bin/activate
pip install -r requirements.txt

# 서버가 뜨는지
uvicorn main:app --port 8000

# 스키마가 깨지지 않았는지
open http://127.0.0.1:8000/docs

# 변경한 엔드포인트를 직접 호출
curl -X POST http://127.0.0.1:8000/api/auth/signup/request-code \
  -H 'Content-Type: application/json' \
  -d '{"phone_number":"010-1234-5678"}'
```

| 조건 | 확인 방법 |
|------|-----------|
| 서버가 예외 없이 기동한다 | `uvicorn main:app` |
| OpenAPI 스키마가 생성된다 | `/docs` 200 |
| 변경/추가한 엔드포인트가 성공·실패 케이스 모두 의도한 응답을 준다 | `curl` 또는 `/docs` |
| API 계약을 바꿨다면 `k-calAI-RN`을 함께 수정했다 | 두 저장소 diff |
| `.env.example`이 새 환경변수를 포함한다 | diff |
| 비밀값이 커밋에 없다 | `git diff --staged` |

## 리뷰 체크리스트

### Correctness

- [ ] `commit()`이 서비스 최상위 진입점에서만 호출되는가. 내부 헬퍼는 `flush()`까지인가.
- [ ] 예외 발생 시 트랜잭션이 열린 채 남지 않는가. (`get_db`의 `finally: db.close()`는 rollback을 하지 않습니다.)
- [ ] `datetime`이 timezone-aware UTC인가. `datetime.utcnow()`를 쓰지 않았는가.
- [ ] `expires_at > now`, `consumed_at.is_(None)` 같은 유효성 조건이 쿼리에 포함되어 있는가.
- [ ] 휴대폰 번호가 저장·조회 양쪽에서 `normalize_phone_number`를 거치는가.
- [ ] DB 스키마를 바꿨다면, `create_all`이 **기존 테이블의 컬럼 변경을 반영하지 않는다**는 점을 고려했는가. (수동 DDL 또는 볼륨 재생성 필요)
- [ ] `select()` + `db.scalar()`를 썼는가. `db.query()` 레거시가 아닌가.

### API 계약

- [ ] 새 라우트가 `include_router(..., prefix="/api")`를 경유하는가. `main.py`에 직접 정의하지 않았는가.
- [ ] `response_model`과 `responses={400: {"model": AuthError}}`가 지정되어 있는가.
- [ ] 실패 응답이 `{"detail": "..."}` 형태인가. `{"error": ...}`가 아닌가.
- [ ] 응답에 ORM 객체나 라이브러리 내부 타입이 새어나가지 않는가.
- [ ] 경로·요청 필드·응답 필드 변경이 있다면 `k-calAI-RN/services/*.ts`와 일치하는가.

### 레이어

- [ ] `api/`에 비즈니스 로직이나 SQLAlchemy 쿼리가 없는가.
- [ ] `services/`가 `fastapi`를 import 하지 않는가.
- [ ] `schemas/`가 `models/`나 `services/`에 의존하지 않는가.

### 보안

- [ ] **`AUTH_INCLUDE_DEV_CODE`가 운영에서 `false`인가.** 기본값이 `true`이므로 미설정 시 인증번호가 응답에 노출됩니다.
- [ ] **`AUTH_CODE_PEPPER`가 기본값(`development-only-pepper`)이 아닌가.**
- [ ] 인증번호가 평문으로 저장되거나 로그에 남지 않는가.
- [ ] 예외 메시지에 스택트레이스·라이브러리명·SQL이 포함되지 않는가.
- [ ] `CORS_ALLOW_ORIGINS`가 운영 환경에서 와일드카드가 아닌가. (`allow_origin_regex`가 localhost를 허용하고 `allow_credentials=True`입니다.)
- [ ] 새 비밀값이 `.env.example`에 **빈 값**으로만 들어갔는가.
- [ ] 사용자 입력이 파일 경로·쿼리에 직접 들어가지 않는가.

### 추론 코드

- [ ] 모델 로딩 위치를 바꿨다면 서버 시작 시간과 첫 요청 지연에 미치는 영향을 확인했는가.
- [ ] 업로드 파일 크기·타입 검증이 있는가. (현재 `/predict`에 없습니다.)
- [ ] 추론 결과를 `{ label, score }`로 정규화해서 반환하는가.
- [ ] 모델 실험 코드가 제품 코드와 같은 커밋에 섞이지 않았는가.

### 테스트

- [ ] <!-- TODO: 확인 필요 - 테스트 프레임워크 미도입. 도입 전까지는 수동 검증 결과를 PR 본문에 기록합니다. -->

## 리뷰 시 흔한 실수

| 실수 | 왜 문제인가 |
|------|-------------|
| `/api/predict`가 있다고 가정 | 실제 경로는 `/predict`입니다. `main.py:46` |
| `/api/gpt-predict`를 수정하려 함 | **존재하지 않는 엔드포인트**입니다. 앱만 호출하고 있습니다. |
| `docs/PROJECT_PLANNING.md`를 현재 구현으로 신뢰 | S3 API, YOLO, HF Inference API는 모두 미구현입니다. |
| `requirements.txt`를 UTF-8로 재저장 | 파일 전체가 diff에 잡힙니다. 인코딩 변환은 별도 커밋으로 분리하세요. |
| `create_all`이 컬럼 변경을 반영한다고 가정 | 신규 테이블만 만듭니다. 기존 테이블은 손대지 않습니다. |
| `dev` 브랜치에 push하면 그 코드가 배포된다고 가정 | 워크플로는 `dev` push에 트리거되지만 서버는 `git pull origin main`을 실행합니다. |
| 배포 환경에 `.env`가 자동 전달된다고 가정 | `deploy.yml`은 원격 셸에 환경변수를 전달하지 않습니다. |
| 세션 토큰이 검증되고 있다고 가정 | 발급만 하고 검증·폐기 코드가 없습니다. |
| `/predict`에 인증이 걸려 있다고 가정 | 공개 엔드포인트입니다. |

## 커밋

- 커밋 메시지는 한국어 `<type>: <요약>` 형식입니다. 관찰된 타입: `feat`, `chore`.
- 모델 성능 작업과 API 안정화 작업을 한 커밋에 섞지 않습니다.
- API 계약 변경 커밋은 `k-calAI-RN` 대응 커밋과 짝을 이룹니다.
