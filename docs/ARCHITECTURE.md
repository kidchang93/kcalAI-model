# ARCHITECTURE

## 모듈 구조

```
kcalAI-model/
├── main.py                     # 앱 생성, CORS, 라우터 등록, startup 훅
├── database.py                 # engine, SessionLocal, Base, CreatedAt·UpdatedAt 시각 컬럼 별칭, get_db, init_db
├── crypto.py                   # 민감정보 AES-256-GCM 암복호화 + EncryptedString 타입 (models·services가 사용)
├── log_utils.py                # get_logger(__name__) — 공통 상위 로거 `kcal` 에 INFO·ERROR 파일 핸들러(+콘솔)를 한 번만 부착
├── api/
│   ├── __init__.py             # 비워 둔다 (라우터는 main.py 가 서브모듈에서 직접 import)
│   ├── dependencies.py         # get_current_user (Bearer 세션 토큰 검증), require_sensitive_consent, 별칭 CurrentUser·ConsentedUser·DB
│   ├── auth_api.py             # /auth/kakao/** (OAuth start·callback·login·signup), /auth/logout
│   ├── predict_api.py          # /predict (업로드 검증 + Gemini 인식, 503 on 실패)
│   ├── health_api.py           # /me/profile, /me/goal, /me/summary, /me/trends, /meals (PUT 전체 교체 포함), /weights
│   ├── consent_api.py          # /me/consents, /me/health-profile, /me/conditions, /me/allergies
│   ├── group_api.py            # /groups/** (생성·목록·상세·참여·펫 참여 + 탈퇴·삭제·멤버 제거·펫 해제)
│   ├── pet_api.py              # /pets/** (등록·목록·수정·삭제·급여 기록)
│   ├── nutrition_api.py        # /nutrition/estimate, /nutrition/warnings (기록 경고 판정, sensitive_health 동의 필수)
│   ├── meta_api.py             # /meta/options (온보딩 선택지 목록)
│   ├── account_api.py          # DELETE /me (회원 탈퇴 — 계정 파기, DATA_MODEL 18장)
│   ├── subscription_api.py     # /plans (무인증), /me/subscription (조회·변경 — PUT은 무료 다운그레이드만, 20·24장)
│   ├── payment_api.py          # /payments, /payments/{id} (결제 내역 읽기 전용, DATA_MODEL 23장)
│   ├── billing_api.py          # /billing/{checkout,confirm,cancel} (자동결제, 24장. BadRequestError→400(전역)·TossError→502·미설정→503)
│   └── recommendation_api.py   # /recommendations (식단 추천, sensitive_health 동의 필수)
├── services/
│   ├── errors.py               # BadRequestError·ForbiddenError·NotFoundError — main.py 전역 핸들러가 400·403·404 {detail} 로 변환
│   ├── auth_service.py         # 카카오 연동코드·OAuth state 서명, 가입·로그인, 세션 생성·검증·폐기 (21장)
│   ├── kakao_client.py         # 카카오 OAuth — 인가 URL·토큰 교환(client_secret)·프로필·연결끊기(unlink)
│   ├── subscription_service.py # 요금제 한도 판정·비전 일일 쿼터(원자적 UPSERT), PlanLimitError (20장), 만료 강등 해석 get_effective_plan (24장)
│   ├── payment_service.py      # 결제 내역 조회·응답 조립 (23장)
│   ├── billing_service.py      # 자동결제 흐름 — checkout·confirm(빌링키 발급·저장·최초 청구)·cancel·갱신 배치, 달력 1개월 (24장)
│   ├── toss_client.py          # 토스페이먼츠 어댑터 — 빌링키 발급·청구, Basic base64("{시크릿}:"), TossError. **키·빌링키 미로깅**
│   ├── health_service.py       # 프로필·목표·끼니·체중·추이 집계, Mifflin-St Jeor
│   ├── consent_service.py      # 동의 이력·유효성 검사(버전이 낡은 민감정보 동의는 무효), 민감정보 파기(물리 삭제)
│   ├── guide_service.py        # /guides 목록의 is_mine — 민감정보 동의가 ACTIVE 일 때만 등록 질환을 읽는다
│   ├── group_service.py        # 그룹 생성·참여, invite_code 생성, 멤버십·펫 참여, 라이프사이클(탈퇴·삭제·제거·해제, 17장)
│   ├── pet_service.py          # 반려동물 CRUD(soft delete), 급여 기록, 접근 권한, 권장 칼로리(RER/MER, 18장)
│   ├── account_service.py      # 회원 탈퇴 — 개인 데이터 물리 삭제 연쇄 (단일 트랜잭션, 18장)
│   ├── nutrition_service.py    # food_nutrition 3단계 조회 (정확→공백 정규화→pg_trgm 유사도, 13장. LLM 없음) + 기록 경고 판정 (16장)
│   ├── food_synonyms.py        # 음식명 동의어·표기 변형 후보 확장 (계란↔달걀 등, 13장)
│   ├── meta_service.py         # 참조 테이블(condition/allergen) 조회·코드 검증, 사용자 연결 참조 행 조회, exclude_keywords 매칭 (추천·경고 공용, 16장)
│   ├── recommendation_service.py # diet_recommendations 캐시 + mfds 후보 풀 + 시드 결정적 규칙 선정 (13장. LLM 없음)
│   ├── gemini_vision_service.py # 이미지 인식(단일 백엔드): Gemini structured JSON → 한글 요리명, 재시도
│   └── upload_validation.py    # 업로드 이미지 크기·타입·디코드 검증 (라우트가 호출)
├── schemas/
│   ├── auth_schema.py          # KakaoLoginRequest, KakaoSignupRequest, AuthTokenResponse
│   ├── subscription_schema.py  # PlanItem, MySubscriptionResponse(+status·기간·다음청구, 24장), PlanLimitErrorResponse (20장)
│   ├── payment_schema.py       # PaymentItem, PaymentsResponse (23장)
│   ├── billing_schema.py       # BillingCheckoutRequest/Response, BillingConfirmRequest (**금액 필드 없음** — 서버가 정한다, 24장)
│   ├── health_schema.py
│   ├── consent_schema.py
│   ├── group_schema.py
│   ├── pet_schema.py           # PetResponse 에 recommended_kcal (계산 필드, 18장)
│   ├── common_schema.py        # ErrorResponse({detail}), MessageResponse({message}) — 전 라우트 공용
│   ├── nutrition_schema.py
│   ├── meta_schema.py          # OptionItem, MetaOptionsResponse
│   ├── recommendation_schema.py # RecommendationItem, ExcludedCriterion/Filtered, RecommendationResponse
│   ├── predict_schema.py       # DetectedFood, PredictionResponse
│   └── gpt_schemas.py          # GptAnswer, GptResponse, GptError
├── models/
│   ├── auth_model.py           # User(kakao_id·nickname), KakaoLinkCode, AuthSession
│   ├── health_model.py         # UserProfile, UserGoal, MealLog, MealItem, WeightLog, FoodNutrition
│   ├── consent_model.py        # UserConsent, UserHealthProfile, UserCondition, UserAllergy
│   ├── group_model.py          # Group, GroupMember, GroupPet
│   ├── pet_model.py            # Pet, PetFeedingLog
│   ├── meta_model.py           # ConditionType, AllergenType (참조 테이블)
│   ├── subscription_model.py   # Plan(참조 테이블), UserSubscription(1:1, +빌링 상태), VisionUsageDaily (20장), BillingKey🔒, Payment (0017·23·24장)
│   └── recommendation_model.py # DietRecommendation (추천 캐시)
├── alembic/                    # DB 마이그레이션 (0001 auth → 0002 health → 0003 consent → 0004 group/pet → 0005 option ref → 0006 diet rec → 0007 food nutrition mfds → 0008 food_label pg_trgm → 0009 meal_items confidence → 0010 condition exclude_keywords → 0011 otp attempt_count → 0012 session token 해시 → 0013 혈액형·Rh 암호화 → 0014 요금제·쿼터 → 0015 카카오 로그인)
├── scripts/
│   ├── import_mfds_food.py     # 식약처 음식 CSV → food_nutrition 임포트 (원본 CSV 는 레포 밖, 커밋 금지)
│   ├── food_upsert.py          # 식약처 임포트 3종(food·processed·raw) 공용 upsert·to_float
│   ├── purge_expired_auth.py   # 만료 연동코드·세션 정리 (멱등, cron)
│   └── charge_due_subscriptions.py  # 자동결제 갱신 배치 (멱등, cron. **실행하면 실제 결제가 일어난다**, 24장)
├── webapp/                     # Expo 웹 빌드 산출물 (gitignored, 존재할 때만 정적 서빙)
│   ├── yolo11n.pt, yolo11n-cls.pt
│   └── classify/
│       ├── korean_food/
│       ├── s3_korean_food_all_classes/weights/last.pt   ← 실사용 가중치
│       ├── s3_korean_food_sequential/                   ← best_v3 ~ v8.2.1
│       └── val/, val2/
├── docker-compose.yml          # postgres:16-alpine
├── .github/workflows/deploy.yml
└── task-logs/                  # 런타임 로그 (gitignored)
```

## 레이어와 의존성 방향

```
api  →  services  →  models  →  database (Base, engine)
 │           │
 └───────────┴──→  schemas
```

| 레이어 | 책임 | 의존해도 되는 것 | 의존하면 안 되는 것 |
|--------|------|------------------|---------------------|
| `api` | HTTP 입출력, 의존성 주입, 예외 변환 | `schemas`, `services`, `database.get_db` | `models` 직접 조작, SQLAlchemy 쿼리, `os.getenv` |
| `services` | 트랜잭션, 비즈니스 규칙, 외부 연동(Gemini) | `models`, `database`, `schemas` | `fastapi` (HTTP 개념) |
| `schemas` | 요청/응답 계약의 단일 기준 | Pydantic | `models`, `services` |
| `models` | 테이블 정의 | `database.Base` | `services`, `api` |
| `database` | 엔진/세션/Base 생성 | 없음 | 상위 레이어 전부 |

**알려진 위반**

현재 없음. (과거 위반이던 `api/file_upload_api.py`의 `os.getenv` 직접 호출과 `str(e)` 노출은 2026-07-12 S3 라우트 제거로 소멸했고, `predict_api`의 `str(e)` 노출은 이전에 로그/응답 분리로 수정됐습니다.)

`database.init_db()`가 `models` 패키지를 함수 내부에서 지연 import 하는 것은 순환 import 회피용(models → database)이며 인정된 예외입니다. 패키지 `__init__`이 전 모델 모듈을 import 하므로 `import models.auth_model` 한 줄도 전 모델을 등록합니다.

## 요청 흐름

### 이미지 인식 (`POST /api/predict`) — Bearer 필수, Gemini 단일 백엔드

```
클라이언트 (multipart/form-data, field=file, Authorization: Bearer <token>)
  └─ api/predict_api.py:predict()
       ├─ current_user: CurrentUser   # get_current_user — 무토큰/무효 토큰 → 401
       ├─ await file.read() → bytes
       ├─ validate_image_upload()      # 크기 413 / 타입 415 / 디코드 400
       ├─ run_in_threadpool(gemini_vision_service.identify_food)   # 블로킹 HTTP → 스레드풀
       │    ├─ Gemini(structured JSON): 한글 요리명 후보 최대 3
       │    ├─ 일시 오류(429·5xx·타임아웃) 백오프 재시도(기본 2회)
       │    └─ [Prediction(label=요리명, score=confidence)]
       ├─ logger.info("predict ok backend=gemini model=... top_label=...")
       └─ {"predictions": [...]}  (response_model=PredictionResponse)

  최종 실패(재시도 소진) → VisionError
  └─ logger.error("predict fail backend=gemini ...")   # 서버에만, 키 미노출
     raise HTTPException(503, detail="음식 인식이 일시적으로 지연되고 있습니다. ...")
     → {"detail": "..."}  (ErrorResponse)
```

칼로리·영양은 앱이 선택한 라벨로 `/api/nutrition/estimate`(식약처 DB)가 계산한다. Gemini는 이름 식별만.

### 레거시 `/api/gpt-predict` — **제거됨 (2026-07-12)**

HF LLM으로 칼로리를 **서술 문자열**로 생성하던 라우트. 앱 신규 흐름은 숫자 kcal이 필요해 `POST /api/nutrition/estimate`(식약처 DB 조회)를 쓰므로 이 라우트를 소비하지 않았다. `api/predict_api.py`의 라우트와 `services/gpt_oss_service.py`·`schemas/gpt_schemas.py`를 삭제해 **`HF_TOKEN` 하드의존(import 시점 `KeyError`)을 제거**했다. `.env` 로딩은 `database.py`·`crypto.py`로 이관했다.

### 인증 — 카카오 로그인 (2026-07-14, 리비전 0015. SMS·OTP 제거)

**서버가 카카오와 토큰을 교환한다.** 카카오는 Redirect URI에 커스텀 스킴(`kcalairn://`)을 등록할 수 없고(http/https만), 신규 REST 키는 `client_secret`이 기본 활성이라 앱이 직접 교환할 수 없다(시크릿을 번들에 넣게 된다).

```
앱(expo-web-browser) ── GET /api/auth/kakao/start?platform=native|web
  └─ api/auth_api.py
       └─ auth_service.create_state()    {platform,nonce,exp} 를 pepper 로 HMAC 서명 (CSRF, 테이블 없음)
       └─ 302 → kauth.kakao.com/oauth/authorize?...&scope=profile_nickname&state=...

카카오 ── GET /api/auth/kakao/callback?code=&state=
  └─ api/auth_api.py
       ├─ auth_service.verify_state()    서명·만료 검증 → StateError 면 딥링크로 error=invalid_state
       ├─ kakao_client.exchange_code()   client_secret 과 함께 토큰 교환 (인가 코드는 1회용)
       ├─ kakao_client.fetch_profile()   /v2/user/me → (회원번호, 닉네임)
       ├─ auth_service.create_link_code() 1회용 연동 코드(TTL 10분) 발급 — DB에는 sha256 해시만
       └─ 302 → kcalairn://auth?code=<연동코드>&is_new=true|false      (웹은 /auth?...)

앱 ── POST /api/auth/kakao/{login|signup}  {link_code, ...}
  └─ services/auth_service.py
       ├─ _consume_link_code()           해시 대조 → consumed_at 기록 (1회용)
       ├─ (signup) 동의 검증 → record_signup_consents() + create_subscription()   ← 한 트랜잭션
       ├─ (login)  닉네임을 카카오 값으로 갱신 (그룹에 보이는 이름이다)
       └─ _create_session()              token_urlsafe(48) 원문은 응답에만, DB에는 sha256 해시 저장
  ← BadRequestError → 400, NotFoundError(미가입) → 404   (main.py 전역 핸들러)
```

**콜백은 JSON이 아니라 리다이렉트로 답한다** — 인앱 브라우저가 여는 화면이라, 실패도 딥링크에 `error=`를 실어 보내야 사용자가 브라우저에 갇히지 않는다.

**회원 탈퇴 시 `kakao_client.unlink()`(어드민 키) 호출은 의무**다. 단 **우리 쪽 파기를 커밋한 뒤** 부르고, 실패해도 예외를 올리지 않는다 — 카카오 장애가 개인정보 파기(법정 의무)를 막으면 안 된다.

### 자동결제 (`POST /api/billing/confirm`) — 2026-07-16, DATA_MODEL 24장

```
앱(토스 결제창이 준 authKey) ── POST /api/billing/confirm {auth_key, customer_key, plan_code}
  └─ api/billing_api.py                     # Bearer. 요청에 **금액 필드가 없다**
       └─ services/billing_service.py
            ├─ get_purchasable_plan()       # 유료·판매중 검증 → amount = plans.price_krw (서버 결정)
            ├─ toss_client.issue_billing_key()   → billingKey + 카드 표시정보
            ├─ billing_keys UPSERT          # billing_key 는 EncryptedString(AES-GCM) 암호화 저장
            ├─ payments INSERT(status=ready) → **commit**   # 원장이 먼저, 트랜잭션 열고 결제사 대기 금지
            ├─ toss_client.charge_billing() → paymentKey·method·approvedAt
            ├─ 성공: payment done + 구독 활성화(period_end=+1개월, next_billing_at=period_end)
            └─ 실패: payment failed(fail_code·fail_reason) + **구독 미활성화** → TossError
  ← BadRequestError → 400(전역) / TossError → **502**(결제사 오류) / TossNotConfiguredError → 503
```

갱신은 `scripts/charge_due_subscriptions.py`(cron) → `charge_due_subscriptions()`가 같은 청구 경로를 탄다. 만료 강등은 행을 바꾸지 않고 `subscription_service.get_effective_plan()`이 **읽을 때 해석**하므로, 비전 쿼터·그룹·펫 한도가 전부 자동으로 만료를 존중한다.

**시크릿 키·빌링키는 로그·응답에 절대 나가지 않는다** — 실패 로그는 `status=400 code=REJECT_CARD_COMPANY` 형태로 결제사 코드만 남긴다.

### 환경 게이트 (`APP_ENV`, 2026-07-12)

`main.py`가 `APP_ENV`(기본 `development`)를 읽어 두 가지를 분기합니다.

- **production 기동 fail-fast**: `auth_service.ensure_production_auth_config()`(`AUTH_CODE_PEPPER` 기본값) + `crypto.ensure_production_crypto_config()`(`HEALTH_ENCRYPTION_KEY` 기본키) + `gemini_client.ensure_api_key()`(`GEMINI_API_KEY` 없음) + **`kakao_client.ensure_production_kakao_config()`**(카카오 키 4종 — 유일한 인증 수단이라 없으면 아무도 로그인 못 한다) + **`toss_client.ensure_production_toss_config()`**(`TOSS_SECRET_KEY`·`TOSS_CLIENT_KEY` — 없으면 유료 요금제를 팔 수 없는데 그 사실이 사용자의 결제 시도에서야 드러나면 안 된다)가 import 단계에서 `RuntimeError`로 죽입니다.

### 이미지 인식 — Gemini 단일 백엔드 (2026-07-12)

이미지 인식은 `services/gemini_vision_service.py:identify_food()` **단일 경로**다(YOLO/torch 제거). 이미지를 Gemini(structured JSON)로 보내 **한글 요리명 후보**를 받고, 일시 오류(타임아웃·429·5xx)는 백오프 재시도(기본 2회, `GEMINI_MAX_RETRIES`) 후 최종 실패 시 `VisionError`로 라우트가 **503**을 반환한다(폴백 없음). Gemini는 **이름 식별만** 하고 칼로리·영양은 `/api/nutrition/estimate`(식약처 DB)가 계산한다 — 반환 라벨이 mfds/curated에 매핑되도록 프롬프트가 한식 요리명을 유도한다. 블로킹 HTTP라 라우트는 `run_in_threadpool`로 호출한다. `GEMINI_API_KEY`는 로그·응답에 노출하지 않는다.
- **CORS**: localhost `allow_origin_regex`는 development에서만 적용. production은 `CORS_ALLOW_ORIGINS` 명시 목록만 신뢰합니다.

### 민감정보 암호화 (`crypto.py`, 2026-07-12, 리비전 0013)

`user_health_profiles.blood_type`·`rh`만 앱 레이어 AES-256-GCM으로 암호화 저장합니다. `crypto.py`의 `EncryptedString`(SQLAlchemy `TypeDecorator`)이 ORM write 시 암호화·read 시 복호화를 투명하게 처리하므로 서비스·직렬화 코드는 평문을 그대로 다룹니다. 키는 `HEALTH_ENCRYPTION_KEY`.

**범위를 혈액형·Rh로 한정한 이유**: 암호문은 DB 레벨 JOIN·WHERE·UNIQUE 대상이 될 수 없습니다(암호문끼리 비교됨). `condition`·`allergen`은 참조 테이블 FK, `meta_service`의 DB JOIN, `(user_id, code)` UNIQUE, 추천/경고 필터에 쓰이는 **기능 키**라 암호화하면 이 전부가 깨집니다. 따라서 이 둘은 평문 코드로 유지합니다 (표준 범주 코드라 자유 PII보다 민감도도 낮음). `blood_type`·`rh`는 어떤 쿼리에도 쓰이지 않는 순수 데이터라 앱 레이어 암호화의 '조회 불가' 단점이 없습니다.

### S3 (`/api/s3/*`) — **제거됨 (2026-07-12)**

NCP Object Storage 자원 중단 확정으로 `api/file_upload_api.py`, `services/s3_service.py`, `schemas/s3_schemas.py`, `http/test_s3.http`와 8개 라우트를 전부 삭제했습니다. `boto3`도 `requirements.txt`에서 제거했습니다. `meals.photo_s3_key` 컬럼(항상 NULL)만 스토리지 재도입 대비로 남아 있습니다 (`docs/DATA_MODEL.md` 4장).

## 웹 정적 서빙 (배포 구조 — `docs/DATA_MODEL.md` 8장)

FastAPI가 Expo 웹 빌드를 서빙하는 **단일 배포 단위**입니다.

```
kcal/build-web.sh → npx expo export --platform web → kcalAI-model/webapp/
                                                      └─ main.py 가 정적 서빙
```

- `main.py`는 **모든 API 라우터를 등록한 뒤** `app.mount("/", StaticFiles(directory="webapp", html=True))` 합니다. 라우트가 mount보다 먼저 매칭되므로 **`/api/**`가 항상 우선**하고, 나머지 경로가 정적 파일로 갑니다.
- `webapp/` 디렉토리가 **없으면 mount 자체를 건너뜁니다** (개발 환경에서 없을 수 있음). 서빙을 켜려면 빌드 산출물을 넣고 서버를 재시작합니다.
- `webapp/`은 빌드 산출물이므로 커밋하지 않습니다 (`.gitignore`).
- 프로덕션 반영은 `deploy.yml`에 export 단계가 필요합니다 (사용자 확인 후 별도 진행).

## 데이터 모델

| 테이블 | 주요 컬럼 | 비고 |
|--------|-----------|------|
| `users` | `id`, `phone_number`(unique), `is_phone_verified`, `created_at`, `updated_at` | 회원 탈퇴(`DELETE /api/me`) 시 개인 데이터 전체와 함께 **물리 삭제** (파기 연쇄는 DATA_MODEL 18장) |
| `phone_verification_codes` | `id`, `phone_number`, `purpose`(`signup`/`login`), `code_hash`, `attempt_count`, `expires_at`, `consumed_at`, `created_at` | 평문 코드 미저장. `attempt_count`(리비전 0011)는 검증 실패 누적, 5회 초과 시 무효화 |
| `auth_sessions` | `id`, `user_id`(FK), `token`(unique), `expires_at`, `revoked_at`, `created_at` | `token`은 sha256 해시 저장 (리비전 0012). 원문은 발급 응답에만 나가고 조회는 해시 비교 |
| `user_profiles` `user_goals` `meal_logs` `meal_items` `weight_logs` `food_nutrition` | `docs/DATA_MODEL.md` 3장 | 리비전 0002. `food_nutrition`은 0007에서 `sugar_g`·`sodium_mg`·`potassium_mg`·`phosphorus_mg`·`food_group` 추가 (식약처 실측, 12장). 적재는 `scripts/import_mfds_food.py` |
| `user_consents` | `id`, `user_id`(FK), `kind`, `version`, `agreed_at`, `revoked_at` | 재동의는 새 행 (이력 보존). 리비전 0003 |
| `user_health_profiles` | `id`, `user_id`(FK, unique), `blood_type`🔒, `rh`🔒, `deleted_at` | 민감정보. 동의 철회 시 **물리 삭제** |
| `user_conditions` | `id`, `user_id`(FK), `condition` — `(user_id, condition)` unique, FK→`condition_types.code` | 〃. 기능 키라 평문 유지 |
| `user_allergies` | `id`, `user_id`(FK), `allergen`, `severity` — `(user_id, allergen)` unique, FK→`allergen_types.code` | 〃. 기능 키라 평문 유지 |

🔒 = `crypto.EncryptedString`로 앱 레이어 AES-256-GCM 암호화 저장 (0013). 범위는 혈액형·Rh뿐.
| `groups` | `id`, `owner_id`(FK), `name`, `kind`, `invite_code`(unique, 서버 생성) | 리비전 0004. API 계약은 `docs/DATA_MODEL.md` 9장, 라이프사이클(탈퇴·삭제·제거·해제)은 17장. 그룹 삭제는 **물리 삭제** (연결 테이블만 함께 삭제, 펫·급여 기록 보존) |
| `group_members` | `id`, `group_id`(FK), `user_id`(FK), `role` — `(group_id, user_id)` unique | 〃 |
| `pets` | `id`, `owner_id`(FK), `name`, `species`, `breed`, `birth_year`, `weight_kg`, `is_neutered`, `deleted_at` | 보호자 1:N, soft delete. 응답의 `recommended_kcal`(RER/MER)은 컬럼이 아니라 계산 필드 (18장) |
| `group_pets` | `id`, `group_id`(FK), `pet_id`(FK) — `(group_id, pet_id)` unique | 사람 멤버와 테이블 분리 (다형성 FK 회피) |
| `pet_feeding_logs` | `id`, `pet_id`(FK), `fed_at`, `food_label`, `amount_g`, `kcal`(nullable) | `kcal`은 수동 입력 유지. 권장 칼로리(RER/MER)는 펫 응답의 계산 필드로 구현 (18장) |
| `diet_recommendations` | `id`, `user_id`(FK), `rec_date`, `meal_type`, `items`(JSONB), `excluded`(JSONB), `source` — `(user_id, rec_date, meal_type)` unique | 리비전 0006. 추천 캐시. 계약은 `docs/DATA_MODEL.md` 11장, 후보 생성·선정은 12·13장 (순수 규칙, `source` 항상 `rule`) |

- 스키마 변경은 **Alembic 리비전으로만** 합니다 (`alembic/versions/`). `create_all`은 신규 테이블 생성용으로만 남아 있습니다.
- 세션 토큰 검증은 `api/dependencies.py:get_current_user`가 담당합니다. `/api/predict`도 2026-07-12부터 Bearer 필수입니다 (무인증 공개 라우트는 Auth 가입·로그인 4종뿐).
- `/api/me/health-profile`·`/api/me/conditions`·`/api/me/allergies`는 유효한 `sensitive_health` 동의(최신 행의 `revoked_at IS NULL` **이고 `version`이 현재 버전** — 2026-09-13)가 없으면 **403**을 반환합니다. 401(미로그인)과 구분됩니다. 판정·문구는 `consent_service.ensure_sensitive_consent`가 정하고, `SensitiveConsentRequiredError`(`ForbiddenError`)를 `main.py` 전역 핸들러가 403으로 바꿀 뿐입니다 (DATA_MODEL 7장).
- 동의 없이 열리는 라우트(`/api/me/summary`·`trends`·`report`, `/api/guides`)는 막지 않고 **읽는 서비스**(`day_nutrition`·`medical_report_service`·`guide_service`)가 동의 상태를 확인해 민감정보 자리만 비웁니다. 민감정보를 읽는 새 경로는 라우트 게이트나 서비스 확인 중 하나를 반드시 거칩니다.

## 전역 초기화 (import 시점)

| 모듈 | 부작용 | 실패 조건 |
|------|--------|-----------|
| `database.py` · `crypto.py` | `load_dotenv()` — **cwd 기준으로 `.env` 탐색** (설정 최하위 모듈, 멱등) | — |
| `log_utils.get_logger` 첫 호출 (로거를 쓰는 모듈 import) | `task-logs/` 디렉토리 생성 + `kcal` 로거에 핸들러 부착 | — |

이 때문에 `import main`만 해도 모델 로드·`.env` 탐색·토큰 조회가 일어납니다. 테스트를 도입하려면 지연 로딩이 선행되어야 합니다.

두 부작용이 모두 **cwd에 묶여 있다**는 점이 중요합니다. 저장소 루트가 아닌 곳에서 실행하면 가중치도, `.env`도 찾지 못합니다.

## 로깅

모듈마다 `logger = log_utils.get_logger(__name__)` 하나를 쓴다 (2026-09-14, 이전의 `setup_level_logger`·`LevelFilter` 대체).

```
kcal (공통 상위 로거, level=INFO, 핸들러는 여기에만 한 번)
 ├─ task-logs/info_log.txt    ← ERROR 미만 (필터 levelno < ERROR)
 ├─ task-logs/error_log.txt   ← ERROR 이상 (handler level=ERROR)
 └─ 콘솔(stderr)              ← 전부 — journalctl·cron 로그(task-logs/cron_*.log)가 받는다
kcal.api.predict_api · kcal.services.toss_client · …  (get_logger 가 kcal. 을 붙인다)
```

- `RotatingFileHandler(maxBytes=1MB, backupCount=5)`, 포맷 `[%(asctime)s] [%(levelname)s] %(message)s`.
- **root 에 핸들러를 달지 않는다.** 서드파티(httpx·urllib3) 로그가 파일로 들어오는데, 토스 요청 URL 에는 빌링키가 실린다.
- `propagate` 는 기본값(True)이다. uvicorn 기본 설정은 root 에 핸들러가 없어 중복 출력이 없고, pytest `caplog` 가 로그를 볼 수 있다(`tests/test_refund_service.py` 의 미로깅 단언).
- 핸들러 부착은 `kcal.handlers` 가 비었을 때만이라 재import·테스트에서 중복되지 않는다.

## 애플리케이션 수명주기

| 시점 | 동작 | 위치 |
|------|------|------|
| import | CORS 오리진 파싱, `load_dotenv()`, 로거 생성 (Gemini 클라이언트는 첫 호출 시 lazy 생성) | `main.py`, `services/*` |
| startup | `init_db()` → `create_all` | `main.py` (`lifespan` 컨텍스트 매니저) |
| 요청마다 | `get_db()`가 세션 yield → finally close | `database.py:21` |

## 외부 시스템

| 시스템 | 용도 | 접점 |
|--------|------|------|
| PostgreSQL 16 | 사용자·인증코드·세션 | `database.py`, `docker-compose.yml` |
| NCP 서버 | 운영 배포 대상 | `.github/workflows/deploy.yml` |

> NCP Object Storage 연동은 2026-07-12에 제거됐습니다 (자원 중단 확정).

## 배포 파이프라인

`.github/workflows/deploy.yml`

```
push → dev 브랜치
  └─ ubuntu-latest
       ├─ actions/checkout@v3
       ├─ NCP_SSH_KEY 를 ~/private-key.pem 으로 저장 (chmod 600)
       ├─ ssh-keyscan NCP_SERVER_IP >> known_hosts
       ├─ scp -r ./*  →  $PROJECT_PATH        # 저장소 전체 복사 (runs/ 제거로 경량화됨)
       └─ ssh 'bash -s' <<'ENDSSH'
            cd $PROJECT_PATH
            pkill -f "uvicorn main:app" || true
            python3 -m venv .venv && source .venv/bin/activate
            pip install -r requirements.txt
            nohup uvicorn main:app --host 0.0.0.0 --port 8000 & disown
          ENDSSH
```

`${{ secrets.* }}`는 Actions가 heredoc 이전에 치환하므로 `<<'ENDSSH'` 인용과 무관하게 값이 들어갑니다.

**남아 있는 문제**

| 문제 | 설명 |
|------|------|
| 무중단 배포 아님 | `pkill` → `pip install` → 기동. 짧은 다운타임 (YOLO 로드 제거로 단축) |
| ~~매 배포마다 70MB 전송~~ | **해소**: YOLO/`runs/` 제거로 저장소·의존성 경량화(venv 1.3GB→~200MB) |
| 원격 `.env` 관리 부재 | 워크플로가 환경변수를 전달하지 않습니다. `.env`가 없으면 기본값 폴백으로 뜨지만(HF_TOKEN 하드의존은 제거됨), 운영 pepper·암호화 키는 반드시 설정해야 합니다(`APP_ENV=production` fail-fast) |
| 원격 Python 버전 미고정 | `python3 -m venv` — 서버의 기본 python3에 의존 |
| 불필요한 step | `- name: Deploy to NCP Server`가 실제로는 `actions/checkout@v3`를 한 번 더 실행합니다 |

<!-- TODO: 확인 필요 - NCP 서버의 .env 배치 경로와 프로세스 관리 방식(systemd 등)을 확인하지 못했습니다. -->
