# CODE_STYLE

린터·포매터가 도입되어 있지 않습니다. 아래 규칙은 **기존 코드에서 실제로 관찰된 패턴**이며, 새 코드는 이를 따릅니다.

## 파일·패키지 배치

| 종류 | 위치 | 파일명 |
|------|------|--------|
| 라우터 | `api/` | `<domain>_api.py` |
| 비즈니스 로직 | `services/` | `<domain>_service.py` |
| Pydantic 계약 | `schemas/` | `<domain>_schema.py` 또는 `<domain>_schemas.py` |
| ORM 모델 | `models/` | `<domain>_model.py` |
| 학습 산출물 | `runs/` | 커밋하지 않음 (기존 74개는 예외) |
| IDE HTTP 요청 | `http/` | `test_<domain>.http` |

> `schemas/`의 파일명은 단수 `_schema.py`를 씁니다 (`auth_schema.py`, `predict_schema.py`).

각 디렉토리는 단일 도메인당 단일 파일입니다. **`api/__init__.py`는 비워 둡니다** — 라우터는 `main.py`가 각 서브모듈에서 직접 import합니다. (예전엔 여기서 재수출하다가 predict→torch가 딸려와 테스트를 무겁게 만들었습니다. 2026-07-12 정리.)

```python
# main.py
from api.auth_api import router as auth_router
from api.predict_api import router as predict_router
```

## 네이밍

| 대상 | 규칙 | 예시 |
|------|------|------|
| 함수·변수 | `snake_case` | `create_signup_code`, `predict_image`, `setup_level_logger` |
| 모듈 내부 전용 함수 | `_` 접두사 | `_get_user_by_phone`, `_hash_code`, `_consume_valid_code` |
| 클래스 | `PascalCase` | `PhoneVerificationCode`, `AuthTokenResponse` |
| 모듈 상수 | `UPPER_SNAKE_CASE` | `CODE_TTL_MINUTES`, `AUTH_CODE_PEPPER` |
| 라우터 객체 | `router` (모듈 내), `<domain>_router` (재수출 시) | `auth_router`, `predict_router` |
| 테이블명 | 복수 `snake_case` | `users`, `phone_verification_codes`, `auth_sessions` |

공개 API 함수는 동사로 시작합니다: `create_*`, `verify_*`, `normalize_*`, `upload_*`.

### 기존 코드의 규칙 위반 (복제하지 말 것)

머지로 들어온 일부 코드가 `camelCase`를 씁니다. **새 코드는 `snake_case`를 따릅니다.**

| 위반 | 위치 | 따라야 할 이름 |
|------|------|----------------|
| (과거 `answerByGptOss20B`·`gptPredict`는 gpt-predict 제거로 삭제됨) | — | 함수는 `snake_case` |

함수명이 모델 버전(`20B`)을 담고 있으나 실제 호출 모델은 `openai/gpt-oss-120b`입니다. **함수명에 모델 버전을 넣지 마세요.**

## import 순서

표준 라이브러리 → 서드파티 → 로컬. 그룹 사이에 빈 줄 1개, 로컬 그룹 앞에는 빈 줄 2개.

```python
import hashlib
import os
import re
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.auth_model import AuthSession, PhoneVerificationCode, User
```

로컬 import는 절대 경로를 씁니다 (`from database import get_db`).

## 타입 힌트

**모든 함수 시그니처에 타입 힌트를 붙입니다.** PEP 604 문법(`X | None`)을 쓰고 `Optional`을 쓰지 않습니다.

```python
def create_signup_code(db: Session, phone_number: str) -> tuple[datetime, str | None]:
def _get_user_by_phone(db: Session, phone_number: str) -> User | None:
def init_db() -> None:
```

`typing.Generator`는 `get_db`에서 사용합니다 (`database.py:21`).

## SQLAlchemy

2.0 스타일만 사용합니다.

```python
# 모델: Mapped + mapped_column
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    phone_number: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    sessions: Mapped[list["AuthSession"]] = relationship(back_populates="user")

# 조회: select() + db.scalar()
return db.scalar(select(User).where(User.phone_number == phone_number))
```

**금지:** `db.query(User).filter(...)` (1.x 레거시 스타일), `declarative_base()`.

- `nullable=False`를 명시합니다.
- 조회 대상 컬럼에 `index=True`를 붙입니다.
- `commit()`은 서비스 함수의 **최상위 진입점**에서만 호출합니다. 내부 헬퍼는 `flush()`까지만 합니다 (`_consume_valid_code`는 `flush`, `verify_login_code`가 `commit`).

## Pydantic

```python
class PhoneNumberRequest(BaseModel):
    phone_number: str = Field(..., min_length=8, max_length=30)


class VerifyPhoneCodeRequest(PhoneNumberRequest):   # 상속으로 필드 재사용
    code: str = Field(..., min_length=4, max_length=8)


class AuthUser(BaseModel):
    ...
    model_config = {"from_attributes": True}        # v2 문법. class Config 금지
```

- 입력 제약은 `Field(...)`로 스키마에 선언합니다.
- ORM 변환은 `model_config = {"from_attributes": True}`. `class Config: orm_mode = True`(v1)는 쓰지 않습니다.
- 기본값이 있는 응답 필드는 스키마에 둡니다 (`token_type: str = "bearer"`).

## FastAPI 라우트

```python
@router.post(
    "/auth/signup/request-code",
    response_model=PhoneCodeResponse,
    responses={400: {"model": AuthError}},
)
def request_signup_code(request: PhoneNumberRequest, db: Session = Depends(get_db)):
    try:
        expires_at, dev_code = create_signup_code(db, request.phone_number)
        return {
            "message": "회원가입 인증번호를 발급했습니다.",
            "expires_at": expires_at,
            "dev_code": dev_code,
        }
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
```

- 요청 바디 파라미터명은 `request`.
- 상태 코드는 `status.HTTP_400_BAD_REQUEST` 상수를 씁니다. 숫자 리터럴을 쓰지 않습니다.
- 예외 재발생 시 `from error`를 붙입니다.
- DB를 만지지 않는 라우트가 아니면 `def`(동기)를 씁니다. 현재 `async def`는 파일 I/O가 있는 `predict`뿐입니다.

## 환경변수

모듈 최상단에서 한 번만 읽어 상수에 담습니다. 함수 안에서 `os.getenv`를 반복 호출하지 않습니다.

```python
CODE_TTL_MINUTES = int(os.getenv("AUTH_CODE_TTL_MINUTES", "5"))
AUTH_INCLUDE_DEV_CODE = os.getenv("AUTH_INCLUDE_DEV_CODE", "true").lower() == "true"
```

새 환경변수를 추가하면 **`.env.example`에 반드시 함께 추가합니다.**

`load_dotenv()`는 `database.py`·`crypto.py`(설정 최하위 모듈)에서 호출합니다. 멱등이라 안전하지만, 새 서비스에서 굳이 추가 호출하지 마세요.

## 로깅

`log_utils.setup_level_logger(level)`로 레벨별 로거를 만듭니다. `LevelFilter` 때문에 **해당 레벨만** 기록됩니다.

```python
import logging
from log_utils import setup_level_logger

info_logger = setup_level_logger(logging.INFO)     # → task-logs/info_log.txt
error_logger = setup_level_logger(logging.ERROR)   # → task-logs/error_log.txt

info_logger.info(f"{file.filename} 정상 수집 완료")
error_logger.error(f"predict 실패 {file.filename}: {e!r}")
```

- `print()`를 쓰지 않습니다.
- **INFO 로거로 `error()`를 호출하면 아무 데도 기록되지 않습니다.** `LevelFilter`가 레코드를 버립니다. 레벨마다 로거를 따로 만드세요.
- 예외는 `{e!r}`로 남깁니다. `str(e)`는 예외 타입을 잃습니다.
- 로그에 인증번호, 토큰, 자격증명을 남기지 않습니다.

## 주석

- 코드로 드러나지 않는 **이유**만 한국어로 짧게 적습니다.
- 함수가 무엇을 하는지 반복 설명하지 않습니다.
- docstring은 강제하지 않습니다.
- **주석 처리된 옛 구현을 남기지 않습니다.** git이 기억합니다.

```python
# 요청마다 로드하면 지연이 크므로 모듈 전역에 둔다. cwd 가 저장소 루트여야 한다.
model = YOLO("runs/classify/s3_korean_food_all_classes/weights/last.pt")
```

## 포맷

- 들여쓰기 4칸, 문자열은 큰따옴표(`"`).
- 최상위 정의 사이에 빈 줄 2개.
- 여러 인자를 줄바꿈할 때는 마지막 인자 뒤에 trailing comma를 붙입니다.
- 줄 길이 상한은 강제되지 않으나 기존 코드는 약 110자를 넘지 않습니다.

## 금지 패턴

| 금지 | 대신 |
|------|------|
| `db.query(Model).filter(...)` | `db.scalar(select(Model).where(...))` |
| `datetime.utcnow()` | `datetime.now(UTC)` |
| `Optional[str]` | `str \| None` |
| `class Config: orm_mode = True` | `model_config = {"from_attributes": True}` |
| `except Exception: return {"error": str(e)}` | `raise HTTPException(...)`. `response_model`이 걸린 라우트에서 `return`으로 다른 형태를 내보내면 **500 평문**이 됩니다 |
| `raise HTTPException(500, detail=str(e))` | 사용자용 한국어 메시지. 내부 예외는 로거로만 |
| `api/`에서 SQLAlchemy 쿼리 작성 | `services/`로 이동 |
| `api/`에서 `os.getenv` 호출 | `services/`가 설정을 읽습니다 |
| `services/`에서 `fastapi` import | `ValueError`/`RuntimeError`를 던지고 `api/`가 변환 |
| 라우트를 `main.py`에 직접 정의 | `api/<domain>_api.py` + `include_router(prefix="/api")` |
| `@app.on_event("startup")` | `lifespan` 컨텍스트 매니저를 씁니다 (2026-07-12 이전 완료) |
| 비밀값 하드코딩 | `os.getenv` + `.env.example` 등록 |
| 절대경로 모델 로드 (`D:/lck_data/...`) | 저장소 상대경로. 단, cwd 의존성을 문서화할 것 |
| 함수명에 모델 버전 포함 (`...GptOss20B`) | 모델은 바뀝니다. 역할로 명명하세요 |
| 미사용 import (`from cProfile import label`) | 삭제 |
| 주석 처리된 옛 구현을 파일에 남기기 | 삭제. git이 기억합니다 |
| `print()` 디버깅 | `log_utils.setup_level_logger(logging.INFO)` |

## 테스트 스타일

pytest를 씁니다 (`requirements-dev.txt`, 실행은 `venv/bin/python -m pytest`). 규칙:

- **서비스 레이어 우선.** 로직은 서비스 함수에 있으므로 `db` 세션을 받는 함수를 직접 호출해 계약(성공·예외·경계)을 고정한다. 예: `tests/test_auth_service.py`.
- **DB 픽스처는 `tests/conftest.py`의 `db`.** 외부 트랜잭션 + `join_transaction_mode="create_savepoint"`로, 서비스 내부 `db.commit()`을 SAVEPOINT로 흡수하고 종료 시 롤백한다 — 대상 DB를 오염시키지 않는다.
- **테스트 데이터는 명시적으로.** 시간 의존 로직(쿨다운·만료)은 `created_at`을 직접 과거로 옮겨 검증한다 (실제 sleep 금지). 공유 DB의 기존 데이터와 겹치지 않는 번호 대역을 쓴다.
- **모듈 상수는 monkeypatch로.** `AUTH_INCLUDE_DEV_CODE` 등 import 시점에 잡힌 값은 `monkeypatch.setattr`로 덮는다.

### API 레이어 테스트 — TestClient (import 시점 부작용 정리 완료)

`api/__init__.py`를 비운 덕에(2026-07-12) `from api.auth_api import router`만 하면 predict→torch가 딸려오지 않습니다. 그래서 특정 라우터만 최소 앱에 올려 `TestClient`로 테스트합니다 — `tests/test_auth_api.py`(request-code 429·400·200, verify) 참조. `get_db`는 conftest의 savepoint 세션으로 오버라이드합니다.

남은 import 시점 부작용(모델을 실제로 올리는 predict 계열 테스트에만 해당):

| 부작용 | 위치 | 회피 |
|--------|------|------|
| `load_dotenv()` (cwd 기준 `.env` 탐색) | `database.py`·`crypto.py` | 저장소 루트에서 실행 |
| `init_db()`가 실제 PostgreSQL에 연결 | `main.py` | 테스트용 `DATABASE_URL`(또는 `TEST_DATABASE_URL`) |
