# kcalAI-model - Knowledge Base

> 이 문서는 Claude가 프로젝트 작업 시 실수를 방지하기 위한 엄격한 기준을 제공합니다.

## 프로젝트 개요

**kcalAI-model**은 헬스케어 앱의 식단 분석 기능을 지원하는 **FastAPI 기반 AI 추론 서버**입니다. 음식 이미지 분류(YOLO), 칼로리 설명 생성(LLM), 휴대폰 인증, S3 오브젝트 스토리지 연동을 담당하며 `k-calAI-RN` 앱이 주 소비자입니다.

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
| 오브젝트 스토리지 | boto3 1.35.83 → NCP Object Storage (S3 호환) |
| 설정 로딩 | `python-dotenv`의 `load_dotenv()` |
| 배포 | GitHub Actions(`dev` 브랜치) → scp → NCP 서버 |
| 테스트 | **없음** (프레임워크 미도입) |

> `torch`는 ultralytics가 내부적으로 사용합니다. 반면 **`transformers`는 어디에서도 호출되지 않습니다** — `predict_service.py`와 `gpt_oss_service.py`가 `pipeline`을 import하지만 사용부가 전부 주석 처리된 로컬 모델 잔재입니다.

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

# 3. 환경변수 (HF_TOKEN 없으면 import 단계에서 죽습니다)
cp .env.example .env
#   .env 에 HF_TOKEN, ACCESS_KEY, SECRET_KEY, REGION, BUCKET_NAME, DOMAIN 채우기

# 4. 서버 실행 (반드시 저장소 루트에서)
uvicorn main:app --reload --port 8000

# 5. API 문서
open http://127.0.0.1:8000/docs
```

**워크스페이스 원클릭 실행기**: `../dev.sh` (Postgres + 서버 + Expo 앱). `../dev.sh server`로 서버만 띄울 수 있습니다.

**식약처 음식 DB 적재** (칼로리 측정 `/api/nutrition/estimate`과 식단 추천의 데이터 원천 — 둘 다 LLM 없이 이 DB만 씁니다, `docs/DATA_MODEL.md` 12·13장): `venv/bin/python scripts/import_mfds_food.py <식약처 음식 CSV 경로>` — 저장소 루트에서 실행, idempotent upsert(재실행 안전). 원본 CSV(`../data/`)는 커밋하지 않습니다.

**식약처 가공식품 DB 선별 적재** (음료·주류·과자·조미료 보강, estimate 전용 — 추천 후보에는 안 들어갑니다, `docs/DATA_MODEL.md` 14장): `venv/bin/python scripts/import_mfds_processed.py <가공식품 xlsx 경로>` — 대표식품명 단위 중앙값 집계(249행), 기존 mfds(요리)·curated 행은 덮지 않습니다.

**원재료성식품 DB 적재** (원물 과일·채소·견과·수산물 보강, estimate 전용, `docs/DATA_MODEL.md` 14장): `venv/bin/python scripts/import_mfds_raw.py <농진청 CSV> <해수부 CSV>` — 일반명 중앙값 집계(1,384행), '생것' 우선·차류는 추출만. 요리·가공식품 행은 덮지 않습니다.

### 반드시 저장소 루트에서 실행할 것

`services/predict_service.py:22`가 가중치를 **상대경로**로 로드합니다.

```python
model = YOLO("runs/classify/s3_korean_food_all_classes/weights/last.pt")
```

다른 cwd에서 uvicorn을 띄우면 import 단계에서 실패합니다.

### 검증 명령어

<!-- TODO: 확인 필요 - lint/format/test 명령어가 정의되어 있지 않습니다. -->

| 목적 | 명령어 |
|------|--------|
| 테스트 | 없음 |
| 린트 | 없음 |
| 포맷 | 없음 |
| 수동 검증 | `uvicorn main:app` 기동 + `/docs` 200 + `http/*.http` 요청 |

---

## 환경변수

`load_dotenv()`는 `services/gpt_oss_service.py`와 `services/s3_service.py`에서만 호출됩니다. 이 모듈들이 import되므로 결과적으로 `.env`가 로드됩니다.

| 변수 | 필수 | 기본값 | 읽는 곳 |
|------|:----:|--------|---------|
| `HF_TOKEN` | **예** | 없음 | `services/gpt_oss_service.py:26` — `os.environ["HF_TOKEN"]`. `.env`와 셸 환경변수 **양쪽 모두에 없으면 import 단계 KeyError** (실측) |
| `DATABASE_URL` | 아니오 | `postgresql+psycopg2://kcal:kcal@localhost:5432/kcal` | `database.py:8` |
| `AUTH_CODE_TTL_MINUTES` | 아니오 | `5` | `services/auth_service.py:13` |
| `AUTH_SESSION_TTL_DAYS` | 아니오 | `30` | `services/auth_service.py:14` |
| `AUTH_CODE_PEPPER` | 아니오 | `development-only-pepper` | 운영에서 **반드시 교체** |
| `AUTH_INCLUDE_DEV_CODE` | 아니오 | `true` | 운영에서 **반드시 `false`** |
| `ACCESS_KEY` `SECRET_KEY` `REGION` `BUCKET_NAME` `DOMAIN` | S3 사용 시 | 없음 | `services/s3_service.py`, `api/file_upload_api.py` |
| `CORS_ALLOW_ORIGINS` | 아니오 | localhost:3000,5173 | `main.py:17` |
| `AIHUB_API_KEY` | — | — | `.env`에만 있고 **코드에서 미사용** |

**`.env.example`이 불완전합니다.** `ACCESS_KEY`, `SECRET_KEY`, `REGION`, `BUCKET_NAME`, `DOMAIN`, `CORS_ALLOW_ORIGINS`가 빠져 있습니다.

---

## API 목록 (코드 실측, 2026-07-11 기준 50개)

계약 상세는 `docs/DATA_MODEL.md`가 정본입니다 (4장 CRUD, 7장 사용자 층, 9장 그룹·반려동물, 10장 메타, 11장 식단 추천, 15장 추이 집계, 16장 기록 경고 판정).

| 도메인 | 라우트 | 정의 파일 |
|--------|--------|-----------|
| Auth | `POST /api/auth/signup/request-code` · `signup/verify` · `login/request-code` · `login/verify` · `logout` | `api/auth_api.py` |
| Predict | `POST /api/predict` · `POST /api/gpt-predict` | `api/predict_api.py` |
| Nutrition | `POST /api/nutrition/estimate` · `POST /api/nutrition/warnings` (Bearer + `sensitive_health` 동의 필수) | `api/nutrition_api.py` |
| Health | `GET·PUT /api/me/profile` · `GET·PUT /api/me/goal` · `GET /api/me/summary` · `GET /api/me/trends` · `POST·GET /api/meals` · `DELETE /api/meals/{meal_id}` · `POST·GET /api/weights` | `api/health_api.py` |
| Consent | `GET·POST /api/me/consents` · `POST /api/me/consents/revoke` · `GET·PUT /api/me/health-profile` · `GET·PUT /api/me/conditions` · `GET·PUT /api/me/allergies` | `api/consent_api.py` |
| Groups | `POST·GET /api/groups` · `POST /api/groups/join` · `GET /api/groups/{group_id}` · `POST /api/groups/{group_id}/pets` | `api/group_api.py` |
| Pets | `POST·GET /api/pets` · `PUT·DELETE /api/pets/{pet_id}` · `POST·GET /api/pets/{pet_id}/feedings` | `api/pet_api.py` |
| Meta | `GET /api/meta/options` | `api/meta_api.py` |
| Recommendations | `GET /api/recommendations` (Bearer + `sensitive_health` 동의 필수, 캐시 우선) | `api/recommendation_api.py` |
| S3 | `POST /api/s3/upload/file` · `upload/local-file` · `upload/directory` · `DELETE /api/s3/delete/{s3_key}` · `delete-prefix/{prefix}` · `GET /api/s3/presigned-url/{s3_key}` · `buckets` · `objects` | `api/file_upload_api.py` |

S3·Predict와 Auth의 가입·로그인 4종을 제외한 전 라우트가 Bearer 인증(`api/dependencies.py`의 `get_current_user`)을 요구합니다 (`/api/auth/logout`도 Bearer 필요). `/api/predict`와 `/api/s3/*`가 무인증 공개인 것은 알려진 문제입니다(아래 표 참고).

---

## 알려진 문제 (작업 전 반드시 인지)

| # | 내용 | 근거 |
|---|------|------|
| 1 | `HF_TOKEN`이 `.env`에도 셸 환경변수에도 없으면 **서버가 아예 뜨지 않습니다** (import 시점 `KeyError`). `load_dotenv()`가 **cwd 기준**으로 `.env`를 찾으므로, 저장소 루트가 아닌 곳에서 실행하면 토큰을 못 찾습니다. | `services/gpt_oss_service.py:15,26` (실측 확인) |
| 2 | `AUTH_INCLUDE_DEV_CODE` 기본값이 `true`라 미설정 시 인증번호가 API 응답에 노출됩니다. | `services/auth_service.py:16,104` |
| 3 | `AUTH_CODE_PEPPER` 기본값이 `development-only-pepper`입니다. | `services/auth_service.py:15` |
| 4 | ~~세션 토큰을 발급만 하고 검증·폐기하는 코드가 없습니다.~~ **해결됨** (2026-07-09). `get_current_user`(`api/dependencies.py`) + `get_user_by_session_token`/`revoke_session_token`(`services/auth_service.py`) + `POST /api/auth/logout`. **단 `/api/predict`, `/api/gpt-predict`, `/api/s3/*`는 여전히 무인증 공개입니다.** | `api/dependencies.py` |
| 5 | `/api/s3/*`가 `detail=f"...: {str(e)}"`로 **boto3 내부 예외를 그대로 노출**합니다. `HTTPException detail` **10곳**(92,95,158,161,204,242,437,505,564,567) + 응답 dict `str(e)` **3곳**(352,386,387) = 총 13곳. (이전 문서의 "14곳"은 실측과 달랐습니다) | `api/file_upload_api.py` |
| 6 | `api/file_upload_api.py`가 `os.getenv`로 자격증명을 직접 읽습니다. 레이어 규칙 위반입니다. | `api/file_upload_api.py` |
| 7 | `DELETE /api/s3/delete-prefix/{prefix}`가 사용자 입력을 검증 없이 prefix로 씁니다. | `api/file_upload_api.py:207` |
| 8 | `@app.on_event("startup")`은 FastAPI 0.118에서 deprecated입니다. lifespan으로 이전이 필요합니다. | `main.py:34` |
| 9 | ~~DB 마이그레이션 도구가 없습니다.~~ **해결됨** (2026-07-09). Alembic 도입 — `alembic/versions/0001_initial_auth.py`, `0002_health_tables.py`. 스키마 변경은 이제 `alembic revision`으로 합니다. `create_all`은 남아 있으나 신규 테이블 생성용입니다. | `alembic.ini`, `database.py:32` |
| 10 | `runs/`에 학습 산출물 74개(약 70MB)가 커밋되어 있습니다. 배포 시 `scp -r ./*`로 매번 전송됩니다. | `.github/workflows/deploy.yml:41` |
| 11 | `.env.example`에 `ACCESS_KEY`, `SECRET_KEY`, `REGION`, `BUCKET_NAME`, `DOMAIN`, `CORS_ALLOW_ORIGINS`가 누락되어 있습니다. | `.env.example` |

---

## 절대 하지 말아야 할 것

- **저장소 루트가 아닌 곳에서 서버를 실행하지 않는다.** YOLO 가중치를 상대경로로 로드합니다.
- **`AUTH_INCLUDE_DEV_CODE`를 운영에서 `true`로 두지 않는다.** 기본값이 `true`입니다.
- **`AUTH_CODE_PEPPER` 기본값을 그대로 배포하지 않는다.**
- **`.env`를 커밋하지 않는다.** `HF_TOKEN`과 NCP 자격증명이 들어 있습니다.
- **예외 메시지를 그대로 클라이언트에 반환하지 않는다.** 내부 예외는 `error_logger`에만 남기고, 클라이언트에는 사용자용 한국어 메시지를 줍니다. `api/file_upload_api.py`의 `detail=f"...: {str(e)}"`(문제 5)를 복제하지 마세요.
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
