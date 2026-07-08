# ARCHITECTURE

## 모듈 구조

```
kcalAI-model/
├── main.py                 # 앱 생성, CORS, 추론 엔드포인트, 라우터 등록, startup 훅
├── database.py             # engine, SessionLocal, Base, get_db, init_db
├── api/
│   ├── __init__.py         # auth_router 재수출
│   └── auth_api.py         # APIRouter: /auth/** (HTTP 경계)
├── services/
│   └── auth_service.py     # 인증 비즈니스 로직 (코드 발급/검증, 세션 생성)
├── schemas/
│   └── auth_schema.py      # Pydantic 요청/응답 계약
├── models/
│   ├── __init__.py
│   └── auth_model.py       # SQLAlchemy ORM: User, PhoneVerificationCode, AuthSession
├── docker-compose.yml      # postgres:16-alpine
├── .github/workflows/
│   └── deploy.yml          # dev 브랜치 push → NCP 배포
└── task-logs/              # 로컬 로그 (gitignored)
```

## 레이어와 의존성 방향

```
api  →  services  →  models  →  database (Base, engine)
 │           │
 └───────────┴──→  schemas
```

| 레이어 | 책임 | 의존해도 되는 것 | 의존하면 안 되는 것 |
|--------|------|------------------|---------------------|
| `api` | HTTP 입출력, 의존성 주입, `ValueError → HTTPException` 변환 | `schemas`, `services`, `database.get_db` | `models` 직접 조작, SQLAlchemy 쿼리 |
| `services` | 트랜잭션, 비즈니스 규칙, 외부 연동 | `models`, `database` | `fastapi` (HTTP 개념) |
| `schemas` | 요청/응답 계약의 단일 기준 | Pydantic | `models`, `services` |
| `models` | 테이블 정의 | `database.Base` | `services`, `api` |
| `database` | 엔진/세션/Base 생성 | 없음 | 상위 레이어 전부 |

**역방향 의존 금지.** 단, `database.init_db()`는 `models.auth_model`을 함수 내부에서 지연 import 하여 테이블 등록만 수행합니다 (`database.py:30`). 이는 순환 import 회피용이며 예외로 인정된 유일한 지점입니다.

## 요청 흐름

### 인증 (`POST /api/auth/{mode}/{action}`)

```
클라이언트
  └─ FastAPI 라우팅
       └─ api/auth_api.py  ── Depends(get_db) → Session
            │  Pydantic이 요청 바디 검증 (schemas/auth_schema.py)
            └─ services/auth_service.py
                 ├─ normalize_phone_number()   숫자만 추출, 82→0 치환, 10~15자리 검증
                 ├─ _get_user_by_phone()       select(User)
                 ├─ _create_phone_code()       6자리 난수 → sha256 해시 저장 → commit
                 │    또는
                 ├─ _consume_valid_code()      해시 대조 + 미소비 + 미만료 → consumed_at 기록
                 └─ _create_session()          token_urlsafe(48), TTL 30일
            ← ValueError 발생 시 api 레이어가 HTTPException(400, detail=str(e))로 변환
       └─ response_model 직렬화 (AuthTokenResponse / PhoneCodeResponse)
```

### 추론 (`POST /predict`)

```
클라이언트 (multipart/form-data, field=file)
  └─ main.py:predict()
       ├─ await file.read()  → bytes
       ├─ PIL.Image.open(io.BytesIO(...))
       ├─ classifier(image)             # 모듈 로드 시점에 생성된 전역 파이프라인
       └─ JSONResponse({"predictions": results[:3]})
          예외 시 JSONResponse({"error": str(e)}, 500)
```

> 이 경로는 `api/` 레이어를 거치지 않고 `main.py`에 직접 정의되어 있습니다. 레이어 규칙의 예외이자 정리 대상입니다.

## 데이터 모델

| 테이블 | 주요 컬럼 | 비고 |
|--------|-----------|------|
| `users` | `id`, `phone_number`(unique), `is_phone_verified`, `created_at`, `updated_at` | |
| `phone_verification_codes` | `id`, `phone_number`, `purpose`(`signup`/`login`), `code_hash`, `expires_at`, `consumed_at`, `created_at` | 평문 코드 미저장 |
| `auth_sessions` | `id`, `user_id`(FK), `token`(unique), `expires_at`, `revoked_at`, `created_at` | `User.sessions` 역참조 |

- 코드 해시: `sha256(f"{PEPPER}:{phone}:{purpose}:{code}")` (`services/auth_service.py:137`)
- 스키마 생성: `Base.metadata.create_all(bind=engine)` — **마이그레이션 도구 없음**. 컬럼 변경은 반영되지 않습니다.
- `AuthSession.revoked_at`, `AuthSession.token`을 검증하는 코드는 **아직 없습니다.** 로그아웃·세션 인증 미들웨어 미구현.

## 모델 로딩

`main.py:35`에서 **모듈 import 시점에** 전역 `classifier` 파이프라인을 생성합니다.

- 최초 실행 시 Hugging Face에서 `nateraw/food` 가중치를 내려받습니다.
- 서버 시작 시간과 메모리 사용량이 여기에 묶입니다.
- 테스트에서 `import main`만 해도 모델이 로드됩니다. 테스트 도입 시 지연 로딩 또는 lifespan 이전이 선행되어야 합니다.

## 외부 시스템

| 시스템 | 용도 | 접점 |
|--------|------|------|
| PostgreSQL 16 | 사용자·인증코드·세션 저장 | `database.py`, `docker-compose.yml` |
| Hugging Face Hub | `nateraw/food` 가중치 다운로드 | `main.py:35` (transformers) |
| NCP 서버 | 운영 배포 대상 | `.github/workflows/deploy.yml` |

## 애플리케이션 수명주기

| 시점 | 동작 | 위치 |
|------|------|------|
| import | CORS 오리진 파싱, `classifier` 로드 | `main.py:15-38` |
| startup | `init_db()` → `create_all` | `main.py:41` (`@app.on_event`, deprecated) |
| 요청마다 | `get_db()`가 세션 yield → finally close | `database.py:21` |

`@app.on_event("startup")`은 FastAPI 0.117에서 deprecated입니다. lifespan 컨텍스트 매니저로의 이전이 필요합니다.

## 배포 파이프라인

`.github/workflows/deploy.yml`

```
push → dev 브랜치
  └─ ubuntu-latest / Python 3.12
       ├─ pip install -r requirements.txt   (Actions 러너에서 - 실제 배포엔 미사용)
       └─ ssh $SERVER_USER@$SERVER_IP
            ├─ git reset --hard && git pull origin main
            ├─ venv 생성/활성화, pip install
            ├─ pkill -f "uvicorn main:app"
            └─ nohup uvicorn main:app --host 0.0.0.0 --port 8000 &
```

**이 워크플로에는 다음 문제가 있습니다. 배포 관련 작업 전에 확인하세요.**

| 문제 | 위치 | 설명 |
|------|------|------|
| 트리거 브랜치와 pull 브랜치 불일치 | `on.push.branches: dev` vs `git pull origin main` | `dev`에 push하면 서버는 `main`을 받습니다 |
| heredoc 변수 미확장 | `<< 'EOF'` | 따옴표로 인해 `$PROJECT_PATH`가 원격에서 확장되지 않아 `cd $PROJECT_PATH`가 홈 디렉토리로 이동합니다 |
| 환경변수 전달 없음 | `ssh` 호출 | `DATABASE_URL`, `AUTH_CODE_PEPPER`, `AUTH_INCLUDE_DEV_CODE`가 원격 셸에 전달되지 않아 **기본값으로 기동**됩니다 |
| 무중단 배포 아님 | `pkill` → `nohup` | 모델 로딩 시간만큼 다운타임이 발생합니다 |

<!-- TODO: 확인 필요 - NCP 서버의 실제 프로세스 관리 방식(systemd/pm2/nohup)과 .env 배치 경로를 확인하지 못했습니다. -->
