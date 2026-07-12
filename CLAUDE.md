# kcalAI-model - Knowledge Base

> 이 문서는 Claude가 프로젝트 작업 시 실수를 방지하기 위한 엄격한 기준을 제공합니다.

## 프로젝트 개요

**kcalAI-model**은 헬스케어 앱의 식단 분석 기능을 지원하는 **FastAPI 기반 AI 추론 서버**입니다. 음식 이미지 분류(YOLO), 칼로리·영양 추정(식약처 DB 조회), 휴대폰 인증을 담당하며 `k-calAI-RN` 앱이 주 소비자입니다. (2026-07-12에 `/api/s3/*`(NCP Object Storage 중단)와 레거시 `/api/gpt-predict`(HF LLM 서술 생성 — 앱 미사용)를 제거했습니다. `meals.photo_s3_key` 컬럼만 선반영 상태로 남아 있습니다.)

메인 제품이 아니라 상위 앱의 기능 서버라는 위치를 유지합니다. 제품 맥락은 `docs/SERVICE_POSITIONING.md`를 참조하세요.

### 핵심 기술 스택

| 항목 | 기술 |
|------|------|
| 프레임워크 | FastAPI 0.118.0 |
| 언어 | Python (로컬 확인: 3.13.5) |
| ASGI 서버 | uvicorn 0.37.0 |
| ORM | SQLAlchemy 2.0.36 (`DeclarativeBase`, `Mapped`) |
| 데이터베이스 | PostgreSQL 16 (docker-compose) |
| 이미지 분류 | ultralytics 8.3.204 (YOLO11 classify) |
| 분류 가중치 | `runs/classify/s3_korean_food_all_classes/weights/last.pt` (한국 음식, 한국어 라벨) |
| 텍스트 생성 | `huggingface_hub.InferenceClient` (provider `groq`, model `openai/gpt-oss-120b`) |
| 설정 로딩 | `python-dotenv`의 `load_dotenv()` |
| 배포 | GitHub Actions(`dev` 브랜치) → scp → NCP 서버 |
| 테스트 | **없음** (프레임워크 미도입) |

> `torch`는 ultralytics가 내부적으로 사용합니다. 반면 **`transformers`는 어디에서도 호출되지 않습니다** — `predict_service.py`가 `pipeline`을 import하지만 사용부가 전부 주석 처리된 로컬 모델 잔재입니다 (별도 정리 후보). `huggingface_hub`도 `gpt_oss_service` 제거로 직접 사용처가 없습니다.

---

## 빌드 및 실행 명령어

```bash
# 1. DB 기동 (필수 - startup 시 init_db 가 연결을 시도함)
docker compose up -d postgres

# 2. 가상환경 + 의존성
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 3. 환경변수 (모두 선택값 — 기본값 폴백이 있어 .env 없이도 로컬 기동됩니다)
cp .env.example .env

# 4. 서버 실행 (반드시 저장소 루트에서)
uvicorn main:app --reload --port 8000

# 5. API 문서
open http://127.0.0.1:8000/docs
```

**워크스페이스 원클릭 실행기**: `../dev.sh` (Postgres + 서버 + Expo 앱). `../dev.sh server`로 서버만 띄울 수 있습니다.

**식약처 음식 DB 적재** (칼로리 측정 `/api/nutrition/estimate`과 식단 추천의 데이터 원천 — 둘 다 LLM 없이 이 DB만 씁니다, `docs/DATA_MODEL.md` 12·13장): `venv/bin/python scripts/import_mfds_food.py <식약처 음식 CSV 경로>` — 저장소 루트에서 실행, idempotent upsert(재실행 안전). 원본 CSV(`../data/`)는 커밋하지 않습니다.

**식약처 가공식품 DB 선별 적재** (음료·주류·과자·조미료 보강, estimate 전용 — 추천 후보에는 안 들어갑니다, `docs/DATA_MODEL.md` 14장): `venv/bin/python scripts/import_mfds_processed.py <가공식품 xlsx 경로>` — 대표식품명 단위 중앙값 집계(249행), 기존 mfds(요리)·curated 행은 덮지 않습니다.

**원재료성식품 DB 적재** (원물 과일·채소·견과·수산물 보강, estimate 전용, `docs/DATA_MODEL.md` 14장): `venv/bin/python scripts/import_mfds_raw.py <농진청 CSV> <해수부 CSV>` — 일반명 중앙값 집계(1,384행), '생것' 우선·차류는 추출만. 요리·가공식품 행은 덮지 않습니다.

**curated 시드 적재** (식약처 범위 밖 라벨 — 외국 요리·생선/일반명 한식·간식·음료 보강, estimate 전용, `docs/DATA_MODEL.md` 14장): `venv/bin/python scripts/seed_curated_foods.py` — 데이터는 스크립트에 인라인으로 커밋(외부 파일 불필요), `source='curated'` 멱등 upsert, `WHERE source='curated'`라 mfds 행은 안 건드립니다. 항목은 스크립트의 `CURATED_FOODS`에 추가하면 됩니다.

**만료 인증 데이터 정리 배치** (`phone_verification_codes`·`auth_sessions` 무한 누적 방지): `venv/bin/python scripts/purge_expired_auth.py` — 만료 코드(발급 1일 뒤)·만료·폐기 세션(7일 뒤)을 물리 삭제, 멱등. 정기 실행(cron/systemd)을 권장. 보존창은 `services/auth_service.py`의 `CODE_RETENTION_DAYS`·`SESSION_RETENTION_DAYS`.

### 반드시 저장소 루트에서 실행할 것

`services/predict_service.py:22`가 가중치를 **상대경로**로 로드합니다.

```python
model = YOLO("runs/classify/s3_korean_food_all_classes/weights/last.pt")
```

다른 cwd에서 uvicorn을 띄우면 import 단계에서 실패합니다.

### 검증 명령어

| 목적 | 명령어 |
|------|--------|
| 테스트 | `venv/bin/python -m pytest` (의존성: `venv/bin/pip install -r requirements-dev.txt`) |
| 린트 | 없음 |
| 포맷 | 없음 |

테스트는 Postgres에 붙습니다 (인증 로직의 tz-aware datetime 충실도). 각 테스트는 외부 트랜잭션 + SAVEPOINT 롤백으로 격리되어 대상 DB를 오염시키지 않습니다. 공유 DB의 기존 데이터와 번호가 겹칠 수 있으니, 깔끔한 격리가 필요하면 `TEST_DATABASE_URL`로 전용 DB를 지정하세요. 현재 커버리지는 `tests/test_auth_service.py` (v18 인증 견고화 회귀).
| 수동 검증 | `uvicorn main:app` 기동 + `/docs` 200 + `http/*.http` 요청 |

---

## 환경변수

`load_dotenv()`는 `database.py`와 `crypto.py`에서 호출됩니다(둘 다 설정을 읽는 최하위 모듈, 멱등). cwd 기준으로 `.env`를 찾으므로 저장소 루트에서 실행합니다.

| 변수 | 필수 | 기본값 | 읽는 곳 |
|------|:----:|--------|---------|
| `DATABASE_URL` | 아니오 | `postgresql+psycopg2://kcal:kcal@localhost:5432/kcal` | `database.py:8` |
| `AUTH_CODE_TTL_MINUTES` | 아니오 | `5` | `services/auth_service.py:13` |
| `AUTH_SESSION_TTL_DAYS` | 아니오 | `30` | `services/auth_service.py:14` |
| `AUTH_CODE_PEPPER` | 아니오 | `development-only-pepper` | 운영에서 **반드시 교체** — `APP_ENV=production`이면 기본값·플레이스홀더 시 기동 실패 (fail-fast) |
| `AUTH_INCLUDE_DEV_CODE` | 아니오 | `true` | 운영에서 **반드시 `false`** — `APP_ENV=production`이면 `true`일 때 기동 실패 |
| `APP_ENV` | 아니오 | `development` | `main.py` — `production`이면 인증 설정 fail-fast + CORS localhost 정규식 비활성 (2026-07-12) |
| `CORS_ALLOW_ORIGINS` | 아니오 | localhost:3000,5173 | `main.py` — production에서는 이 명시 목록만 허용 |
| `PREDICT_MAX_UPLOAD_MB` | 아니오 | `10` | `api/predict_api.py` — 업로드 상한(초과 시 413). 리버스 프록시 `client_max_body_size`와 함께 방어 |
| `HEALTH_ENCRYPTION_KEY` | 아니오 | 개발 기본키 | `crypto.py` — 민감정보(혈액형·질병·알러지) AES-256-GCM 키(base64 32B). `APP_ENV=production`이면 기본키일 때 기동 실패 |
| `VISION_BACKEND` | 아니오 | `yolo` | `main.py`·`api/predict_api.py` — 이미지 인식 백엔드. `gemini`면 predict가 Gemini 사용(실패 시 YOLO 폴백) |
| `GEMINI_API_KEY` | 아니오 | 없음 | `services/gemini_vision_service.py` — `VISION_BACKEND=gemini`일 때 필요. `APP_ENV=production`+`gemini`면 없을 때 기동 실패. **로그·응답에 미노출** |
| `GEMINI_MODEL` | 아니오 | `gemini-flash-latest` | 〃 — 재현성 필요 시 핀 버전(예: `gemini-3.5-flash`) |
| `GEMINI_TIMEOUT_MS` | 아니오 | `15000` | 〃 — Gemini 호출 타임아웃(ms) |
| `AIHUB_API_KEY` | — | — | `.env`에만 있고 **코드에서 미사용** |

(`ACCESS_KEY` 등 S3 자격증명 5종은 S3 제거로 더 이상 읽지 않습니다 — `.env`에 남아 있어도 무해합니다.)

---

## API 목록 (코드 실측, 2026-07-12 기준 47개)

계약 상세는 `docs/DATA_MODEL.md`가 정본입니다 (4장 CRUD, 7장 사용자 층, 9장 그룹·반려동물, 10장 메타, 11장 식단 추천, 15장 추이 집계, 16장 기록 경고 판정, 17장 그룹 라이프사이클, 18장 회원 탈퇴·펫 권장 칼로리).

| 도메인 | 라우트 | 정의 파일 |
|--------|--------|-----------|
| Auth | `POST /api/auth/signup/request-code` · `signup/verify` · `login/request-code` · `login/verify` · `logout` | `api/auth_api.py` |
| Predict | `POST /api/predict` (Bearer 필수, `sensitive_health` 동의 불필요, 업로드 검증 413/415/400) | `api/predict_api.py` |
| Nutrition | `POST /api/nutrition/estimate` (Bearer만 — 질병·알러지 미사용이라 동의 불필요) · `POST /api/nutrition/warnings` (Bearer + `sensitive_health` 동의 필수) | `api/nutrition_api.py` |
| Health | `GET·PUT /api/me/profile` · `GET·PUT /api/me/goal` · `GET /api/me/summary` · `GET /api/me/trends` · `POST·GET /api/meals` · `PUT·DELETE /api/meals/{meal_id}` · `POST·GET /api/weights` | `api/health_api.py` |
| Consent | `GET·POST /api/me/consents` · `POST /api/me/consents/revoke` · `GET·PUT /api/me/health-profile` · `GET·PUT /api/me/conditions` · `GET·PUT /api/me/allergies` | `api/consent_api.py` |
| Groups | `POST·GET /api/groups` · `POST /api/groups/join` · `GET·DELETE /api/groups/{group_id}` · `DELETE /api/groups/{group_id}/members/me` · `DELETE /api/groups/{group_id}/members/{user_id}` · `POST /api/groups/{group_id}/pets` · `DELETE /api/groups/{group_id}/pets/{pet_id}` | `api/group_api.py` |
| Pets | `POST·GET /api/pets` · `PUT·DELETE /api/pets/{pet_id}` · `POST·GET /api/pets/{pet_id}/feedings` | `api/pet_api.py` |
| Meta | `GET /api/meta/options` | `api/meta_api.py` |
| Account | `DELETE /api/me` (회원 탈퇴 — 개인 데이터 전부 물리 삭제, 소유 그룹은 그룹째 삭제. `docs/DATA_MODEL.md` 18장) | `api/account_api.py` |
| Recommendations | `GET /api/recommendations` (Bearer + `sensitive_health` 동의 필수, 캐시 우선) | `api/recommendation_api.py` |

Auth의 가입·로그인 4종(`signup/request-code`, `signup/verify`, `login/request-code`, `login/verify`)을 제외한 **전 라우트**가 Bearer 인증(`api/dependencies.py`의 `get_current_user`)을 요구합니다 (`/api/auth/logout`도 Bearer 필요). `/api/predict`는 2026-07-12에 Bearer 필수로 전환했습니다. 같은 날 `/api/s3/*` 8개 라우트(NCP Object Storage 중단)와 레거시 `/api/gpt-predict`(HF LLM 서술 생성 — 앱 미사용, HF_TOKEN 하드의존)를 제거했습니다.

---

## 알려진 문제 (작업 전 반드시 인지)

| # | 내용 | 근거 |
|---|------|------|
| 1 | ~~`HF_TOKEN`이 없으면 서버가 import 시점 `KeyError`로 안 뜬다.~~ **해소** (2026-07-12): 유일 소비처 `gpt_oss_service.py`(`/api/gpt-predict`)를 제거해 HF_TOKEN 하드의존이 사라졌습니다. `load_dotenv()`는 이제 `database.py`·`crypto.py`가 호출하며 **cwd 기준**이라 저장소 루트에서 실행해야 `.env`를 찾습니다. | `database.py`, `crypto.py` |
| 2 | `AUTH_INCLUDE_DEV_CODE` 기본값이 `true`라 미설정 시 인증번호가 API 응답에 노출됩니다. **완화됨** (2026-07-12): `APP_ENV=production`이면 `true`일 때 기동 자체가 실패합니다 (`ensure_production_auth_config`). | `services/auth_service.py` |
| 3 | `AUTH_CODE_PEPPER` 기본값이 `development-only-pepper`입니다. **완화됨** (2026-07-12): `APP_ENV=production`이면 기본값·플레이스홀더일 때 기동 실패. | `services/auth_service.py` |
| 4 | ~~세션 토큰을 발급만 하고 검증·폐기하는 코드가 없습니다.~~ **해결됨** (2026-07-09). `get_current_user`(`api/dependencies.py`) + `get_user_by_session_token`/`revoke_session_token`(`services/auth_service.py`) + `POST /api/auth/logout`. ~~단 `/api/predict`, `/api/gpt-predict`는 무인증 공개~~ → **해결됨** (2026-07-12, 둘 다 Bearer 필수). | `api/dependencies.py`, `api/predict_api.py` |
| 5 | ~~`/api/s3/*`가 `str(e)`로 boto3 내부 예외를 노출 (13곳).~~ **소멸** (2026-07-12). S3 라우트 제거로 `api/file_upload_api.py` 자체가 삭제됐습니다. | — |
| 6 | ~~`api/file_upload_api.py`가 `os.getenv`로 자격증명을 직접 읽음.~~ **소멸** (2026-07-12, 파일 삭제). | — |
| 7 | ~~`DELETE /api/s3/delete-prefix/{prefix}` prefix 미검증.~~ **소멸** (2026-07-12, 라우트 제거). | — |
| 8 | ~~`@app.on_event("startup")` deprecated~~ **해소** (2026-07-12): `lifespan` 컨텍스트 매니저로 이전. | `main.py` |
| 9 | ~~DB 마이그레이션 도구가 없습니다.~~ **해결됨** (2026-07-09). Alembic 도입 — `alembic/versions/0001_initial_auth.py`, `0002_health_tables.py`. 스키마 변경은 이제 `alembic revision`으로 합니다. `create_all`은 남아 있으나 신규 테이블 생성용입니다. | `alembic.ini`, `database.py:32` |
| 10 | `runs/`에 학습 산출물 74개(약 70MB)가 커밋되어 있습니다. 배포 시 `scp -r ./*`로 매번 전송됩니다. | `.github/workflows/deploy.yml:41` |
| 11 | ~~`.env.example`에 `CORS_ALLOW_ORIGINS`가 누락되어 있습니다.~~ **해결됨** (2026-07-12). `APP_ENV`·`CORS_ALLOW_ORIGINS` 추가. (S3 자격증명 5종은 S3 제거로 더 이상 필요 없습니다) | `.env.example` |

---

## 절대 하지 말아야 할 것

- **저장소 루트가 아닌 곳에서 서버를 실행하지 않는다.** YOLO 가중치를 상대경로로 로드합니다.
- **`AUTH_INCLUDE_DEV_CODE`를 운영에서 `true`로 두지 않는다.** 기본값이 `true`입니다.
- **`AUTH_CODE_PEPPER` 기본값을 그대로 배포하지 않는다.**
- **`.env`를 커밋하지 않는다.** `HF_TOKEN`과 NCP 자격증명이 들어 있습니다.
- **예외 메시지를 그대로 클라이언트에 반환하지 않는다.** 내부 예외는 `error_logger`에만 남기고, 클라이언트에는 사용자용 한국어 메시지를 줍니다. `detail=f"...: {str(e)}"` 패턴(삭제된 `api/file_upload_api.py`에 있던 안티패턴)을 복제하지 마세요.
- **`response_model`이 걸린 라우트에서 실패를 `return`하지 않는다.** 검증에 걸려 500 평문이 나갑니다. `raise HTTPException(...)`을 씁니다.
- **INFO 로거로 `.error()`를 호출하지 않는다.** `setup_level_logger`의 `LevelFilter`가 레코드를 버립니다. `error_logger = setup_level_logger(logging.ERROR)`를 따로 만듭니다.
- **`api` 레이어에 비즈니스 로직이나 `os.getenv`를 넣지 않는다.** HTTP 입출력과 예외 변환만 담당합니다.
- **DB 스키마를 변경할 때 마이그레이션 없이 진행하지 않는다.**
- **모델 성능 실험과 제품 API 안정화를 같은 커밋에 섞지 않는다.**
- **API 계약을 바꾸면서 `k-calAI-RN`을 함께 확인하지 않고 끝내지 않는다.**
- **`runs/`에 새 가중치를 추가로 커밋하지 않는다.** 이미 70MB입니다. 별도 스토리지 이전을 먼저 논의합니다.

---

## docs 인덱스

| 작업 | 먼저 읽을 문서 |
|------|----------------|
| **헬스케어 확장 · 신규 테이블/API** | **`docs/DATA_MODEL.md`** (확정 사양서) |
| 모듈 구조·의존성 파악 | `docs/ARCHITECTURE.md` |
| 새 엔드포인트/스키마 추가 | `docs/DESIGN.md` → `docs/ARCHITECTURE.md` |
| 코드 작성 직전 | `docs/CODE_STYLE.md` |
| 리뷰·머지 전 | `docs/REVIEW.md` |
| 서브에이전트 실행 | `docs/SUBAGENTS.md` |
| 제품 맥락·API 책임 범위 | `docs/PROJECT_PLANNING.md`, `docs/SERVICE_POSITIONING.md` |
| 세션 운영·변경 관리 규칙 | `docs/PROJECT_CONVENTIONS.md` |

---

## 브랜치

| 브랜치 | 역할 |
|--------|------|
| `master` | 기본 브랜치 (`origin/HEAD`) |
| `dev` | **배포 트리거.** push하면 NCP 서버로 배포됩니다 |
| `ck-local` | 로컬 작업 브랜치 |

## 연관 저장소

`k-calAI-RN` (Expo/React Native 앱) — 이 서버의 주 소비자입니다.
API 계약 변경은 두 저장소를 **같은 작업 단위**에서 수정합니다.
