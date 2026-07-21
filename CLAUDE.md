# kcalAI-model - Knowledge Base

> 이 문서는 Claude가 프로젝트 작업 시 실수를 방지하기 위한 엄격한 기준을 제공합니다.

## 프로젝트 개요

**kcalAI-model**은 헬스케어 앱의 식단 분석 기능을 지원하는 **FastAPI 기반 AI 추론 서버**입니다. 음식 이미지 인식(Gemini 비전), 칼로리·영양 추정(식약처 DB 조회), 카카오 로그인 인증, 요금제·쿼터를 담당하며 `k-calAI-RN` 앱이 주 소비자입니다. (2026-07-12에 `/api/s3/*`(NCP Object Storage 중단)와 레거시 `/api/gpt-predict`(HF LLM 서술 생성 — 앱 미사용)를 제거했습니다. `meals.photo_s3_key` 컬럼만 선반영 상태로 남아 있습니다.)

메인 제품이 아니라 상위 앱의 기능 서버라는 위치를 유지합니다. 제품 맥락은 `docs/SERVICE_POSITIONING.md`를 참조하세요.

### 핵심 기술 스택

| 항목 | 기술 |
|------|------|
| 프레임워크 | FastAPI 0.118.0 |
| 언어 | Python (로컬 확인: 3.13.5) |
| ASGI 서버 | uvicorn 0.37.0 |
| ORM | SQLAlchemy 2.0.36 (`DeclarativeBase`, `Mapped`) |
| 데이터베이스 | PostgreSQL 16 (docker-compose) |
| 인증 | 카카오 로그인 (REST, 서버 주도 OAuth) — `services/kakao_client.py` |
| 이미지 인식 | Google Gemini 비전 (`google-genai`, 단일 백엔드) — `services/gemini_vision_service.py` |
| 영양 추정 | 식약처 DB 조회가 원칙. **미등록 라벨만** Gemini로 1회 추정 후 DB 동결 — `services/gemini_nutrition_service.py` (19장) |
| Gemini 공용 어댑터 | 클라이언트·재시도·structured JSON 파싱 — `services/gemini_client.py` (비전·영양 추정이 공유) |
| 설정 로딩 | `python-dotenv`의 `load_dotenv()` |
| 배포 | AWS Lightsail (Ubuntu, systemd + Caddy) — `deploy/DEPLOY.md` |
| 테스트 | pytest (`venv/bin/python -m pytest`) |

> **2026-07-12: YOLO/torch 완전 제거.** Lightsail 경량 배포를 위해 `services/predict_service.py`(ultralytics/torch/transformers)와 `runs/` 가중치(70MB)를 삭제하고, 이미지 인식을 **Gemini 단일 백엔드**로 전환했습니다. venv 1.3GB→~200MB. estimate/추천은 식약처 DB·정적 데이터라 이 제거에 무영향입니다.

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

**로컬 로그인** (카카오 우회 — 알려진 문제 12): `venv/bin/python scripts/dev_login.py --conditions ckd` — 실제 가입·로그인 경로를 그대로 태워 세션을 발급하고, 온보딩 가드를 통과하도록 프로필·목표·민감정보 동의까지 채웁니다. 출력된 `localStorage.setItem(...)` 한 줄을 앱 오리진(기본 `http://localhost:8081`) 브라우저 콘솔에 붙여넣으면 로그인 상태가 됩니다. 계정은 `local-dev:<label>`로 구분되며 **`APP_ENV=production`이면 실행을 거부**합니다.

**식약처 음식 DB 적재** (칼로리 측정 `/api/nutrition/estimate`과 식단 추천의 데이터 원천 — 둘 다 LLM 없이 이 DB만 씁니다, `docs/DATA_MODEL.md` 12·13장): `venv/bin/python scripts/import_mfds_food.py <식약처 음식 CSV 경로>` — 저장소 루트에서 실행, idempotent upsert(재실행 안전). 원본 CSV(`../data/`)는 커밋하지 않습니다.

**식약처 가공식품 DB 선별 적재** (음료·주류·과자·조미료 보강, estimate 전용 — 추천 후보에는 안 들어갑니다, `docs/DATA_MODEL.md` 14장): `venv/bin/python scripts/import_mfds_processed.py <가공식품 xlsx 경로>` — 대표식품명 단위 중앙값 집계(249행), 기존 mfds(요리)·curated 행은 덮지 않습니다.

**원재료성식품 DB 적재** (원물 과일·채소·견과·수산물 보강, estimate 전용, `docs/DATA_MODEL.md` 14장): `venv/bin/python scripts/import_mfds_raw.py <농진청 CSV> <해수부 CSV>` — 일반명 중앙값 집계(1,384행), '생것' 우선·차류는 추출만. 요리·가공식품 행은 덮지 않습니다.

**curated 시드 적재** (식약처 범위 밖 라벨 — 외국 요리·생선/일반명 한식·간식·음료 보강, estimate 전용, `docs/DATA_MODEL.md` 14장): `venv/bin/python scripts/seed_curated_foods.py` — 데이터는 스크립트에 인라인으로 커밋(외부 파일 불필요), `source='curated'` 멱등 upsert, `WHERE source='curated'`라 mfds 행은 안 건드립니다. 항목은 스크립트의 `CURATED_FOODS`에 추가하면 됩니다.

**자주 먹는 음식 1인분 보정** (식약처 식품중량이 비현실적으로 작아 과소평가되던 요리·원물의 1인분을 현실화 — "칼로리가 너무 작게 나온다" 해소, `docs/DATA_MODEL.md` 14장): `venv/bin/python scripts/correct_common_foods.py` — 데이터 인라인, **source 제한 없이 덮어써** mfds/raw 행도 보정하고 `source='curated'`로 바꿔 재적재에도 유지합니다. 계산 **모델(1인분×serving_ratio)은 불변**이고 값만 보정합니다(제육볶음 202→430·떡볶이 193→360·사과 52→95 등 31건). 항목·값은 `CORRECTIONS`에서 조정합니다.

**자동결제 갱신 배치** (청구 예정일이 지난 구독을 청구 — `docs/DATA_MODEL.md` 24장): `venv/bin/python scripts/charge_due_subscriptions.py` — 저장소 루트에서 실행, **멱등**(성공 건은 `next_billing_at`이 한 달 뒤로 밀려 재실행 시 대상에서 빠짐). 하루 1회 cron 권장. 한 건의 실패가 배치를 멈추지 않으며 실패 건은 `past_due`로 다음날 재시도합니다. `TOSS_SECRET_KEY` 미설정 시 실행을 거부합니다(exit 1). **실행하면 실제 결제가 일어납니다.**

**만료 인증 데이터 정리 배치** (`kakao_link_codes`·`auth_sessions` 무한 누적 방지): `venv/bin/python scripts/purge_expired_auth.py` — 만료 코드(발급 1일 뒤)·만료·폐기 세션(7일 뒤)을 물리 삭제, 멱등. 정기 실행(cron/systemd)을 권장. 보존창은 `services/auth_service.py`의 `CODE_RETENTION_DAYS`·`SESSION_RETENTION_DAYS`.

### 반드시 저장소 루트에서 실행할 것

`load_dotenv()`가 **cwd 기준**으로 `.env`를 찾습니다(`database.py`·`crypto.py`). 저장소 루트가 아닌 곳에서 실행하면 `.env`를 못 찾아 설정이 기본값으로 떨어집니다.

다른 cwd에서 uvicorn을 띄우면 import 단계에서 실패합니다.

### 검증 명령어

| 목적 | 명령어 |
|------|--------|
| 테스트 | `venv/bin/python -m pytest` (의존성: `venv/bin/pip install -r requirements-dev.txt`) |
| 린트 | 없음 |
| 포맷 | 없음 |

테스트는 Postgres에 붙습니다 (인증 로직의 tz-aware datetime 충실도). 각 테스트는 외부 트랜잭션 + SAVEPOINT 롤백으로 격리되어 대상 DB를 오염시키지 않습니다. 공유 DB의 기존 데이터와 번호가 겹칠 수 있으니, 깔끔한 격리가 필요하면 `TEST_DATABASE_URL`로 전용 DB를 지정하세요. 현재 **116건**이며 커버리지는 `test_auth_service.py`·`test_auth_api.py`(카카오 로그인, 21장), `test_subscription_service.py`(요금제·쿼터, 20장), `test_billing_service.py`(자동결제, 24장), `test_toss_client.py`(**토스 어댑터의 비밀값 미유출**, 2026-07-16), `test_payment_service.py`(결제 내역, 23장), `test_crypto.py`, `test_upload_validation.py`, `test_web_spa.py`입니다.
| 카카오 설정 진단 | `venv/bin/python scripts/check_kakao_config.py` (읽기 전용. 로그인 실패 시 **원인 판정** — 허용 IP 미등록/키 종류 혼동) |
| 수동 검증 | `uvicorn main:app` 기동 + `/docs` 200 + `http/*.http` 요청 |

---

## 환경변수

`load_dotenv()`는 `database.py`와 `crypto.py`에서 호출됩니다(둘 다 설정을 읽는 최하위 모듈, 멱등). cwd 기준으로 `.env`를 찾으므로 저장소 루트에서 실행합니다.

| 변수 | 필수 | 기본값 | 읽는 곳 |
|------|:----:|--------|---------|
| `DATABASE_URL` | 아니오 | `postgresql+psycopg2://kcal:kcal@localhost:5432/kcal` | `database.py:8` |
| `AUTH_SESSION_TTL_DAYS` | 아니오 | `30` | `services/auth_service.py:14` |
| `AUTH_CODE_PEPPER` | 아니오 | `development-only-pepper` | 세션·연동코드 해시와 **OAuth state 서명**에 쓰인다. 운영에서 **반드시 교체** — 기본값이면 기동 실패 |
| `APP_ENV` | 아니오 | `development` | `main.py` — `production`이면 인증 설정 fail-fast + CORS localhost 정규식 비활성 (2026-07-12) |
| `CORS_ALLOW_ORIGINS` | 아니오 | localhost:3000,5173 | `main.py` — production에서는 이 명시 목록만 허용 |
| `PREDICT_MAX_UPLOAD_MB` | 아니오 | `10` | `api/predict_api.py` — 업로드 상한(초과 시 413). 리버스 프록시 `client_max_body_size`와 함께 방어 |
| `HEALTH_ENCRYPTION_KEY` | 아니오 | 개발 기본키 | `crypto.py` — 민감정보(혈액형·질병·알러지) AES-256-GCM 키(base64 32B). `APP_ENV=production`이면 기본키일 때 기동 실패 |
| `GEMINI_API_KEY` | 사실상 예 | 없음 | `services/gemini_vision_service.py` — 이미지 인식(단일 백엔드)에 필요. `APP_ENV=production`이면 없을 때 기동 실패. **로그·응답에 미노출** |
| `GEMINI_MODEL` | 아니오 | `gemini-flash-latest` | 〃 — 재현성 필요 시 핀 버전(예: `gemini-3.5-flash`) |
| `GEMINI_TIMEOUT_MS` | 아니오 | `15000` | 〃 — Gemini 호출 타임아웃(ms) |
| `TOSS_SECRET_KEY` | production 예 | 없음 | `services/toss_client.py` — 자동결제. **비밀값.** 이 값만으로 임의 청구가 가능하다. Basic `base64("{키}:")` 인증. `APP_ENV=production`이면 없을 때 기동 실패. **로그·응답에 미노출** |
| `TOSS_CLIENT_KEY` | production 예 | 없음 | 〃 — **공개값.** 결제창 SDK 초기화용으로 `/api/billing/checkout` 응답에 실려 앱에 내려간다 |
| `TOSS_TIMEOUT_SECONDS` | 아니오 | `10` | 〃 — 토스 호출 타임아웃(초) |
| `KAKAO_REST_API_KEY` | 예 | 없음 | `services/kakao_client.py` — 인가 URL에 실려 나가는 **공개값** |
| `KAKAO_CLIENT_SECRET` | 예 | 없음 | 〃 — **비밀값.** 신규 REST 키는 기본 활성이라 없으면 토큰 교환 실패 |
| `KAKAO_ADMIN_KEY` | 예 | 없음 | 〃 — **비밀값.** 회원 탈퇴 시 카카오 연결 끊기(unlink) |
| `KAKAO_REDIRECT_URI` | 예 | localhost | 〃 — 카카오 콘솔 등록값과 **문자 단위로 동일**해야 한다(다르면 KOE006). 운영은 https 강제 |
| `APP_DEEPLINK_SCHEME` | 아니오 | `kcalairn` | `api/auth_api.py` — 콜백이 앱으로 되돌아가는 딥링크 스킴 |
| `AIHUB_API_KEY` | — | — | `.env`에만 있고 **코드에서 미사용** |

(`ACCESS_KEY` 등 S3 자격증명 5종은 S3 제거로 더 이상 읽지 않습니다 — `.env`에 남아 있어도 무해합니다.)

---

## API 목록 (openapi.json 실측, 2026-07-16 기준 **55개**)

계약 상세는 `docs/DATA_MODEL.md`가 정본입니다 (4장 CRUD, 7장 사용자 층, 9장 그룹·반려동물, 10장 메타, 11장 식단 추천, 15장 추이 집계, 16장 기록 경고 판정, 17장 그룹 라이프사이클, 18장 회원 탈퇴·펫 권장 칼로리, 23장 결제 내역, **24장 자동결제**).

| 도메인 | 라우트 | 정의 파일 |
|--------|--------|-----------|
| Auth | `GET /api/auth/kakao/start` · `GET /api/auth/kakao/callback` · `POST /api/auth/kakao/login` · `POST /api/auth/kakao/signup` · `POST /api/auth/logout` | `api/auth_api.py` |
| Subscription | `GET /api/plans` (**무인증** — 가입 화면이 로그인 전에 그린다) · `GET·PUT /api/me/subscription` (**PUT은 무료(lite) 다운그레이드만** — 유료 전환은 400, 결제를 거쳐야 한다. 24장) | `api/subscription_api.py` |
| Payments | `GET /api/payments` (내 결제 내역, 최신순) · `GET /api/payments/{id}` (본인 것만, 없거나 남의 것이면 **404** 존재 은닉) — **읽기 전용 조회**. 원장은 빌링 흐름(24장)이 쓴다 (DATA_MODEL 23장) | `api/payment_api.py` |
| Billing | `POST /api/billing/checkout` (결제창 값 발급) · `POST /api/billing/confirm` (카드 등록 + 최초 청구 → 구독 활성화) · `POST /api/billing/cancel` (자동갱신 해지, 기간까지는 유료) — 전부 Bearer. **금액은 서버가 `plans.price_krw`에서 정한다**(요청에 금액 필드 없음). 실패: 400 · **502**(결제사 오류) · 503(키 미설정) (DATA_MODEL 24장) | `api/billing_api.py` |
| Predict | `POST /api/predict` (Bearer 필수, `sensitive_health` 동의 불필요, 업로드 검증 413/415/400. 사진 1장에서 **서로 다른 음식들**을 각각 인식해 `foods`(label·score·portion_g, 최대 10)로 반환 — 한 음식의 후보 나열이 아니다, 22장. **요금제 일일 쿼터 선차감 → 초과 시 402**(쿼터는 사진당 1건, 음식 개수 무관), 인식 실패 시 환불. 응답 후 **백그라운드로 인식된 전 음식 라벨을 영양 DB에 적재** — `prewarm_labels`, 19장) | `api/predict_api.py` |
| Nutrition | `POST /api/nutrition/estimate` (Bearer만 — 질병·알러지 미사용이라 동의 불필요. 미등록 라벨은 LLM 1회 추정 후 `source='llm'`로 동결 적재, 실패 404 / 추정 백엔드 장애 503 — `docs/DATA_MODEL.md` 19장. **응답에 `serving_size_g: float\|None`**(1인분이 몇 g, ml은 밀도≈1로 g 취급, 미상 NULL)이 있어 앱이 사용자 입력 g으로 kcal을 재환산한다 — 리비전 0019, 앱 계약 변경) · `POST /api/nutrition/warnings` (Bearer + `sensitive_health` 동의 필수) | `api/nutrition_api.py` |
| Health | `GET·PUT /api/me/profile` · `GET·PUT /api/me/goal` · `GET /api/me/summary` · `GET /api/me/trends` · `POST·GET /api/meals` · `PUT·DELETE /api/meals/{meal_id}` · `POST·GET /api/weights` | `api/health_api.py` |
| Consent | `GET·POST /api/me/consents` · `POST /api/me/consents/revoke` · `GET·PUT /api/me/health-profile` · `GET·PUT /api/me/conditions` · `GET·PUT /api/me/allergies` | `api/consent_api.py` |
| Groups | `POST·GET /api/groups` · `POST /api/groups/join` · `GET·DELETE /api/groups/{group_id}` · `DELETE /api/groups/{group_id}/members/me` · `DELETE /api/groups/{group_id}/members/{user_id}` · `POST /api/groups/{group_id}/pets` · `DELETE /api/groups/{group_id}/pets/{pet_id}` | `api/group_api.py` |
| Pets | `POST·GET /api/pets` · `PUT·DELETE /api/pets/{pet_id}` · `POST·GET /api/pets/{pet_id}/feedings` | `api/pet_api.py` |
| Meta | `GET /api/meta/options` | `api/meta_api.py` |
| Account | `DELETE /api/me` (회원 탈퇴 — 개인 데이터 전부 물리 삭제, 소유 그룹은 그룹째 삭제. `docs/DATA_MODEL.md` 18장) | `api/account_api.py` |
| Exercises | `GET /api/exercise-types` · `POST·GET /api/exercises` · `PUT·DELETE /api/exercises/{id}` · `GET /api/me/exercise-summary` · `GET·PUT /api/me/exercise-goal` (운동 기록·주간 목표 — 식단과 같은 규약: UTC 자정 경계·soft delete·404 존재 은닉. **플랫폼 중립** — 앱·웹 동일, 기기 연동은 `source`가 느는 입력 경로일 뿐. DATA_MODEL 25장, `docs/ACTIVITY_GUIDANCE.md`) | `api/exercise_api.py` |
| Recommendations | `GET /api/recommendations` (Bearer + `sensitive_health` 동의 필수, 캐시 우선) | `api/recommendation_api.py` |

Auth의 카카오 4종(`kakao/start`, `kakao/callback`, `kakao/login`, `kakao/signup`)과 `GET /api/plans`를 제외한 **전 라우트**가 Bearer 인증(`api/dependencies.py`의 `get_current_user`)을 요구합니다 (`/api/auth/logout`도 Bearer 필요). `/api/predict`는 2026-07-12에 Bearer 필수로 전환했습니다. 같은 날 `/api/s3/*` 8개 라우트(NCP Object Storage 중단)와 레거시 `/api/gpt-predict`(HF LLM 서술 생성 — 앱 미사용, HF_TOKEN 하드의존)를 제거했습니다.

### 인증 = 카카오 로그인 단일 수단 (2026-07-14, 21장)

휴대폰 OTP(SMS)를 **제거**했습니다 — `phone_verification_codes` 테이블, `services/sms_service.py`(Solapi), 가입·로그인 4라우트가 전부 사라졌습니다. 로그인 식별자는 **카카오 회원번호**(`users.kakao_id`)입니다.

- **카카오는 Redirect URI에 커스텀 스킴을 등록할 수 없고** `client_secret`이 사실상 필수라, **토큰 교환은 서버가** 합니다. 앱은 `expo-web-browser`로 `/api/auth/kakao/start`만 열고, 서버가 딥링크(`kcalairn://auth?code=...&is_new=...`)로 되돌려줍니다.
- 카카오 인가 코드는 1회용이라, 신규 회원의 약관 동의·요금제 선택을 위해 **1회용 연동 코드**(`kakao_link_codes`, TTL 10분)를 거칩니다.
- 그룹 멤버 표시가 `phone_number_masked` → **`nickname`**(카카오 닉네임)으로 바뀌었습니다.
- **회원 탈퇴 시 카카오 연결 끊기(unlink) 호출은 의무**입니다 (어드민 키 방식, `services/kakao_client.py`).
- ⚠️ **무료 티어 어뷰징 방어가 없습니다.** 카카오계정은 이메일만으로 만들 수 있어 Lite 3건/일은 계정 갈아타기로 우회됩니다. 감수한 트레이드오프이며, 방어가 필요해지면 서버 측 레이트리밋으로 해결합니다 (21장).

### 요금제 한도 — 402 Payment Required (2026-07-14, 20장)

회원은 요금제 하나를 1:1로 갖습니다 (`user_subscriptions`, 기본 **Lite = 무료**). 한도 초과는 어느 라우트에서든 **402 + 동일 본문**(`{"detail", "code":"plan_limit_exceeded", "resource", "plan", "limit"}`)입니다 — `main.py`의 전역 예외 핸들러가 `PlanLimitError`를 변환합니다. `429`(레이트리밋, 기다리면 풀림)와 구분됩니다.

| code | 가격 | 비전 LLM/일 | 그룹 추가 인원(본인 제외) | 반려동물 | 소유 그룹 |
|---|---:|---:|---:|---:|---:|
| `lite` | 무료 | 5 | 1 | 1 | 1 |
| `pro` | 5,000원 | 30 | 5 | 5 | 3 |
| `premium` | 10,000원 | 100 | 10 | 10 | 5 |

Lite 비전 쿼터는 2026-07-16에 3 → **5**로 상향(리비전 0016, 22장). 쿼터는 **KST 자정** 리셋(`timeutil.today_kst()`)이며, 그룹 자원의 한도는 **그룹 소유자의 요금제**로 판정합니다. 가입(`signup/verify`)은 이제 `agreed_terms`·`agreed_privacy`가 **필수**입니다.

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
| 10 | ~~`runs/`에 학습 산출물 74개(약 70MB)가 커밋되어 있습니다.~~ **해소** (2026-07-12): YOLO 제거와 함께 `runs/`를 삭제했습니다. | — |
| 11 | ~~`.env.example`에 `CORS_ALLOW_ORIGINS`가 누락되어 있습니다.~~ **해결됨** (2026-07-12). `APP_ENV`·`CORS_ALLOW_ORIGINS` 추가. (S3 자격증명 5종은 S3 제거로 더 이상 필요 없습니다) | `.env.example` |
| 12 | **카카오 앱에 허용 IP 제한이 걸려 있어 로컬에서 로그인이 안 됩니다** (2026-07-21 확인). 콘솔에 등록된 IP(운영 서버)가 아닌 곳에서 호출하면 `kapi.kakao.com`이 `-401 "ip mismatched"`를 줍니다. **토큰 교환은 `kauth`라 성공**하고 `/v2/user/me`만 실패해 로그인 직전에 `kakao_unavailable`로 끝나므로 원인을 오해하기 쉽습니다. 공인 IP는 재할당으로 바뀌어 등록해도 또 막히므로, **로컬은 카카오 로그인을 쓰지 않고 `scripts/dev_login.py`로 우회**하기로 했습니다 (2026-07-21 결정). 운영은 서버 IP가 고정이라 정상 동작합니다. 진단: `scripts/check_kakao_config.py` | `services/kakao_client.py` |

---

## 절대 하지 말아야 할 것

- **저장소 루트가 아닌 곳에서 서버를 실행하지 않는다.** `load_dotenv()`가 cwd 기준으로 `.env`를 찾습니다.
- **`AUTH_CODE_PEPPER` 기본값을 그대로 배포하지 않는다.**
- **`.env`를 커밋하지 않는다.** `HF_TOKEN`과 NCP 자격증명이 들어 있습니다.
- **예외 메시지를 그대로 클라이언트에 반환하지 않는다.** 내부 예외는 `error_logger`에만 남기고, 클라이언트에는 사용자용 한국어 메시지를 줍니다. `detail=f"...: {str(e)}"` 패턴(삭제된 `api/file_upload_api.py`에 있던 안티패턴)을 복제하지 마세요.
- **`response_model`이 걸린 라우트에서 실패를 `return`하지 않는다.** 검증에 걸려 500 평문이 나갑니다. `raise HTTPException(...)`을 씁니다.
- **INFO 로거로 `.error()`를 호출하지 않는다.** `setup_level_logger`의 `LevelFilter`가 레코드를 버립니다. `error_logger = setup_level_logger(logging.ERROR)`를 따로 만듭니다.
- **`api` 레이어에 비즈니스 로직이나 `os.getenv`를 넣지 않는다.** HTTP 입출력과 예외 변환만 담당합니다.
- **DB 스키마를 변경할 때 마이그레이션 없이 진행하지 않는다.**
- **모델 성능 실험과 제품 API 안정화를 같은 커밋에 섞지 않는다.**
- **API 계약을 바꾸면서 `k-calAI-RN`을 함께 확인하지 않고 끝내지 않는다.**
- **무거운 ML 의존성(torch·ultralytics·transformers)을 다시 들이지 않는다.** 이미지 인식은 Gemini API로 처리합니다(Lightsail 경량 배포).
- **네이티브 카카오 SDK를 도입하지 않는다.** 얻는 건 카톡 앱-투-앱 UX뿐인데 iOS/Android 네이티브 설정·키해시가 붙고 **웹 빌드가 깨집니다**(웹은 FastAPI가 서빙합니다). REST 방식으로 앱·웹을 통일합니다 (21장).
- **카카오 `client_secret`·어드민 키를 앱에 넣지 않는다.** `EXPO_PUBLIC_*`는 번들에 평문 노출됩니다. 토큰 교환은 **서버에서만** 합니다.
- **회원 탈퇴에서 카카오 unlink를 빼먹지 않는다.** 카카오 로그인 서비스의 의무입니다. 단 **파기를 커밋한 뒤** 호출하고, unlink 실패가 개인정보 파기를 막지 않게 합니다.
- **동의 문서를 개정하면 서버 상수(`consent_service`의 `TERMS_VERSION`·`PRIVACY_VERSION`·`SENSITIVE_HEALTH_VERSION`)와 앱 문서(`k-calAI-RN`의 `constants/legal.ts`·`constants/consent.ts`)를 같은 작업 단위에서 올린다.** 서버만 올리면 기존 앱 사용자의 가입·동의가 전부 400이 됩니다(`ensure_current_version`). 앱이 보낸 버전을 대조해 기록하는 이유는 증빙 때문입니다 — 앱이 v1.0을 띄워 놓고 서버가 "2.0에 동의함"으로 기록하면 그 이력은 거짓입니다 (18장 아래 절).
- **`users`를 참조하는 테이블을 추가하면 `account_service.delete_account`에 반드시 반영한다.** FK가 전부 `ON DELETE NO ACTION`이라, 빠뜨리면 그 데이터를 가진 회원은 `ForeignKeyViolation` → **500으로 영구히 탈퇴할 수 없습니다**(= 개인정보 파기 의무 위반). 2026-07-16에 `payments`·`billing_keys` 누락으로 실제 발생했습니다 — 리비전 0017이 테이블을 추가했는데 2026-07-11에 작성된 삭제 연쇄가 그대로였습니다. `tests/test_account_service.py`가 FK 전수와 삭제 목록을 대조하니, 새 테이블은 그 테스트의 `handled` 집합에도 추가하세요.
- **결제 원장(`payments`)을 탈퇴 시 삭제하지 않는다.** 개인정보는 파기하되(제21조) 대금결제 기록은 보존해야 해서(전자상거래법 제6조), `user_id`만 NULL로 끊어 **익명화**합니다 (18장). 반대로 **`billing_keys`는 반드시 파기**합니다 — 거래 기록이 아니라 카드 재청구 자격증명입니다.
- **결제 검증 없이 유료 플랜을 부여하지 않는다.** 유료 부여 경로는 **`POST /api/billing/confirm`(실제 청구 성공) 하나뿐**입니다. `PUT /api/me/subscription`은 2026-07-16부터 **무료(lite)로만** 바꿀 수 있고(유료 전환은 400), 가입(`POST /api/auth/kakao/signup`)의 `plan_code`도 **유료를 고르면 무료로 시작**합니다(의사표시로만 받음 — 가입을 400으로 막으면 서비스 진입 자체가 실패하므로). 새 부여 경로를 만들 때도 이 원칙을 지키세요.
- **`TOSS_SECRET_KEY`·`billingKey`를 로그·응답·에러 메시지에 남기지 않는다.** 시크릿 키는 이 값만으로 임의 청구가 가능하고, 빌링키는 그 회원 카드의 재청구 자격증명입니다. 로그에는 결제사 **코드**만 남깁니다(`code=REJECT_CARD_COMPANY`). 앱에 내려가는 키는 `client_key`(공개값)뿐입니다.
- **클라이언트가 보낸 결제 금액을 신뢰하지 않는다.** 금액은 언제나 서버가 `plans.price_krw`에서 정합니다 — 요청 스키마에 금액 필드 자체를 두지 않습니다 (`BillingConfirmRequest`). 받으면 100원짜리 Premium이 팔립니다.
- **토스 API를 테스트에서 실제로 호출하지 않는다.** 테스트 키라도 결제사 트래픽입니다. `toss_client`를 monkeypatch로 대체합니다 (`tests/test_billing_service.py`).
- **결제 실패 시 구독을 활성화하지 않는다.** 청구 예외가 나면 구독 행을 건드리지 않습니다 — 결제 안 된 Pro가 생기면 안 됩니다.
- **`confirm`의 중복 방어를 `order_id`·`_mark_payment_done`에 기대지 않는다.** 그 둘은 **주문번호가 같아야** 걸리는 갱신 배치의 방어선인데, `confirm`은 호출마다 새 `order_id`를 만듭니다. 중복은 **구독 상태**로 판정합니다 (`_is_duplicate_confirm` — 같은 플랜 + `active` + 기간 남음이면 청구 없이 200). 이 게이트를 지우면 새로고침·502 후 재시도·결제창 2회 완주가 그대로 이중 결제가 됩니다(방어 전 실측: 5,000원 2회 청구). 단 `past_due`·`canceled`·다른 플랜은 **통과시켜야** 합니다 — 카드를 바꿔 복구하거나 업그레이드하는 정당한 경로입니다 (24장).
- **만료 강등에서 `plan_code`를 덮어쓰지 않는다.** 만료는 **읽을 때 해석**합니다 (`get_effective_plan`). 행을 lite로 쓰면 갱신 배치가 청구 대상을 잃고 이력이 사라집니다 (24장).
- **`PlanLimitError`를 `ValueError`로 바꾸지 않는다.** api 모듈의 `except ValueError → 400`에 잡혀 업그레이드 유도가 일반 입력 오류로 뭉개집니다.
- **비전 쿼터를 Gemini 호출 성공 후에 차감하지 않는다.** 동시 요청이 전부 한도를 통과합니다. 선차감 → 실패 시 환불이 규약입니다.
- **`estimate` 조회 경로에 LLM을 넣지 않는다.** LLM은 **미등록 라벨을 1회 적재할 때만** 씁니다. 조회는 항상 DB를 읽습니다 — 같은 음식이 요청마다 다른 kcal을 내면 안 됩니다 (`docs/DATA_MODEL.md` 13·19장).
- **`source='llm'` 행에 유사도(trgm) 매칭을 허용하지 않는다.** 추정값에 유사도를 얹으면 한 번의 오추정이 이름이 비슷한 다른 음식들로 번집니다. llm 행은 **정확·공백무시 일치만** 반환합니다.
- **LLM 추정값을 게이트 없이 적재하지 않는다.** 적재된 값은 동결되어 자정되지 않습니다. 범위·매크로 정합성 검증을 통과 못 하면 **버리고 404**입니다.

---

## docs 인덱스

| 작업 | 먼저 읽을 문서 |
|------|----------------|
| **헬스케어 확장 · 신규 테이블/API** | **`docs/DATA_MODEL.md`** (확정 사양서) |
| 신장병(CKD) 식이 규칙·근거 | `docs/CKD_NUTRITION.md` |
| BMI·활동량·헬스 앱 연동 | `docs/ACTIVITY_GUIDANCE.md` (기획·근거. 착수 전 §0-1 결정 필요) |
| 모듈 구조·의존성 파악 | `docs/ARCHITECTURE.md` |
| 새 엔드포인트/스키마 추가 | `docs/DESIGN.md` → `docs/ARCHITECTURE.md` |
| 코드 작성 직전 | `docs/CODE_STYLE.md` |
| 리뷰·머지 전 | `docs/REVIEW.md` |
| 서브에이전트 실행 | `docs/SUBAGENTS.md` |
| 제품 맥락·API 책임 범위 | `docs/PROJECT_PLANNING.md`, `docs/SERVICE_POSITIONING.md` |
| 세션 운영·변경 관리 규칙 | `docs/PROJECT_CONVENTIONS.md` |

---

## 브랜치 · 배포

| 브랜치 | 역할 |
|--------|------|
| `master` | 기본 브랜치(`origin/HEAD`)이자 **배포 기준**. 작업 브랜치를 여기 머지한 뒤 배포합니다 |
| `dev` | ~~배포 트리거(NCP)~~ **사문화.** `deploy.yml`이 `dev` push → NCP 배포로 남아 있으나 dev를 push하지 않으므로 아무 일도 하지 않습니다. NCP Object Storage도 중단됐습니다 |
| `release` | ~~배포 브랜치~~ **방치됨** (2026-07-12에 멈춤, master보다 22커밋 뒤). 쓰지 마세요 — 이걸 pull하던 `deploy/redeploy.sh`는 2026-07-16에 `master` 기준으로 고쳤습니다 |
| `ck-local` | 로컬 작업 브랜치 |

**배포는 `bash deploy/local_deploy.sh --web --migrate`** (Lightsail, 운영 `https://api.kcalai.link`). SSH 설정은 `deploy/deploy.local.env`에 있습니다. 절차·주의는 **`deploy/DEPLOY.md`가 정본**입니다.

- ⚠️ **이 스크립트는 git이 아니라 현재 작업 트리를 rsync합니다** — 브랜치도 커밋 여부도 보지 않습니다. 배포 전 `git status`로 확인하세요. 커밋하지 않은 편집도 그대로 운영에 올라갑니다.
- **`git push`는 배포를 트리거하지 않습니다.** push는 GitHub 원격만 갱신합니다.
- 마이그레이션이 있는 배포에서 `--migrate`를 빠뜨리면 새 코드가 옛 스키마를 씁니다.

## 연관 저장소

`k-calAI-RN` (Expo/React Native 앱) — 이 서버의 주 소비자입니다.
API 계약 변경은 두 저장소를 **같은 작업 단위**에서 수정합니다.
