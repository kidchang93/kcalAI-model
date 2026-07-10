# ARCHITECTURE

## 모듈 구조

```
kcalAI-model/
├── main.py                     # 앱 생성, CORS, 라우터 등록, startup 훅
├── database.py                 # engine, SessionLocal, Base, get_db, init_db
├── log_utils.py                # 레벨별 RotatingFileHandler 로거 팩토리
├── api/
│   ├── __init__.py             # 라우터 재수출
│   ├── dependencies.py         # get_current_user (Bearer 세션 토큰 검증)
│   ├── auth_api.py             # /auth/**
│   ├── predict_api.py          # /predict, /gpt-predict
│   ├── health_api.py           # /me/profile, /me/goal, /me/summary, /meals, /weights
│   ├── consent_api.py          # /me/consents, /me/health-profile, /me/conditions, /me/allergies
│   ├── group_api.py            # /groups/** (생성·목록·상세·참여·펫 참여)
│   ├── pet_api.py              # /pets/** (등록·목록·수정·삭제·급여 기록)
│   ├── nutrition_api.py        # /nutrition/estimate
│   ├── meta_api.py             # /meta/options (온보딩 선택지 목록)
│   ├── recommendation_api.py   # /recommendations (식단 추천, sensitive_health 동의 필수)
│   └── file_upload_api.py      # S3 업로드·삭제·조회 (8 라우트)
├── services/
│   ├── auth_service.py         # 인증 코드 발급/검증, 세션 생성·검증·폐기
│   ├── health_service.py       # 프로필·목표·끼니·체중, Mifflin-St Jeor
│   ├── consent_service.py      # 동의 이력·유효성 검사, 민감정보 파기(물리 삭제)
│   ├── group_service.py        # 그룹 생성·참여, invite_code 생성, 멤버십·펫 참여
│   ├── pet_service.py          # 반려동물 CRUD(soft delete), 급여 기록, 접근 권한
│   ├── nutrition_service.py    # food_nutrition 3단계 조회 (정확→공백 정규화→pg_trgm 유사도, 13장. LLM 없음)
│   ├── food_synonyms.py        # 음식명 동의어·표기 변형 후보 확장 (계란↔달걀 등, 13장)
│   ├── meta_service.py         # 참조 테이블(condition/allergen) 조회·코드 검증
│   ├── recommendation_service.py # diet_recommendations 캐시 + mfds 후보 풀 + 시드 결정적 규칙 선정 (13장. LLM 없음)
│   ├── predict_service.py      # YOLO 분류
│   ├── gpt_oss_service.py      # HF InferenceClient (groq) 텍스트 생성
│   └── s3_service.py           # S3Service 클래스 (boto3)
├── schemas/
│   ├── auth_schema.py
│   ├── health_schema.py
│   ├── consent_schema.py
│   ├── group_schema.py
│   ├── pet_schema.py
│   ├── nutrition_schema.py
│   ├── meta_schema.py          # OptionItem, MetaOptionsResponse
│   ├── recommendation_schema.py # RecommendationItem, ExcludedCriterion/Filtered, RecommendationResponse
│   ├── predict_schema.py       # Prediction, PredictionResponse, ErrorResponse
│   ├── gpt_schemas.py          # GptAnswer, GptResponse, GptError
│   └── s3_schemas.py
├── models/
│   ├── auth_model.py           # User, PhoneVerificationCode, AuthSession
│   ├── health_model.py         # UserProfile, UserGoal, MealLog, MealItem, WeightLog, FoodNutrition
│   ├── consent_model.py        # UserConsent, UserHealthProfile, UserCondition, UserAllergy
│   ├── group_model.py          # Group, GroupMember, GroupPet
│   ├── pet_model.py            # Pet, PetFeedingLog
│   ├── meta_model.py           # ConditionType, AllergenType (참조 테이블)
│   └── recommendation_model.py # DietRecommendation (추천 캐시)
├── alembic/                    # DB 마이그레이션 (0001 auth → 0002 health → 0003 consent → 0004 group/pet → 0005 option ref → 0006 diet rec → 0007 food nutrition mfds → 0008 food_label pg_trgm)
├── scripts/
│   └── import_mfds_food.py     # 식약처 음식 CSV → food_nutrition 임포트 (원본 CSV 는 레포 밖, 커밋 금지)
├── webapp/                     # Expo 웹 빌드 산출물 (gitignored, 존재할 때만 정적 서빙)
├── runs/                       # YOLO 학습 산출물 74개 (약 70MB, 커밋됨)
│   ├── yolo11n.pt, yolo11n-cls.pt
│   └── classify/
│       ├── korean_food/
│       ├── s3_korean_food_all_classes/weights/last.pt   ← 실사용 가중치
│       ├── s3_korean_food_sequential/                   ← best_v3 ~ v8.2.1
│       └── val/, val2/
├── http/                       # IDE용 HTTP 요청 파일
│   ├── test_main.http
│   └── test_s3.http
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
| `services` | 트랜잭션, 비즈니스 규칙, 외부 연동(YOLO/HF/S3) | `models`, `database`, `schemas` | `fastapi` (HTTP 개념) |
| `schemas` | 요청/응답 계약의 단일 기준 | Pydantic | `models`, `services` |
| `models` | 테이블 정의 | `database.Base` | `services`, `api` |
| `database` | 엔진/세션/Base 생성 | 없음 | 상위 레이어 전부 |

**알려진 위반**

| 위반 | 위치 |
|------|------|
| `api`가 `os.getenv`로 S3 자격증명을 직접 읽음 | `api/file_upload_api.py` |
| `services`가 `HTTPException` 대신 `RuntimeError`를 던짐(허용) 하지만 `predict_api`가 `str(e)`를 노출 | `api/predict_api.py:27,39` |

`database.init_db()`가 `models.auth_model`을 함수 내부에서 지연 import 하는 것은 순환 import 회피용이며 인정된 예외입니다 (`database.py:30`).

## 요청 흐름

### 이미지 분류 (`POST /api/predict`)

```
클라이언트 (multipart/form-data, field=file)
  └─ api/predict_api.py:predict()
       ├─ await file.read() → bytes
       ├─ services/predict_service.py:predict_image()
       │    ├─ Image.open(BytesIO).convert("RGB")
       │    ├─ model(image)              # 모듈 로드 시 생성된 전역 YOLO
       │    └─ probs.top5[:3] → [Prediction(label, score)]   # 한국어 라벨
       ├─ info_logger.info("<filename> 정상 수집 완료")
       └─ {"predictions": [...]}  (response_model=PredictionResponse)

  실패 시
  └─ error_logger.error("predict 실패 <filename>: <repr(예외)>")   # 서버에만
     raise HTTPException(500, detail="이미지 분석에 실패했습니다. ...")
     → {"detail": "..."}  (ErrorResponse)
```

### 칼로리 설명 (`POST /api/gpt-predict`)

```
클라이언트 { text, max_tokens }
  └─ api/predict_api.py:gptPredict()
       └─ services/gpt_oss_service.py:answerByGptOss20B()
            └─ InferenceClient(provider="groq").chat.completions.create(
                   model="openai/gpt-oss-120b", messages=[{role:user, content:text}])
            └─ GptResponse(response_text=...)
       ← 예외 시 error_logger 에 기록 후
         HTTPException(500, detail="칼로리 설명을 생성하지 못했습니다. ...")
```

함수·모델 이름이 `gpt_oss_20B`지만 실제 호출 모델은 **`openai/gpt-oss-120b`**, 프로바이더는 **groq**입니다.

### 인증 (`POST /api/auth/{mode}/{action}`)

```
api/auth_api.py  ── Depends(get_db) → Session
  └─ services/auth_service.py
       ├─ normalize_phone_number()   숫자만 추출, 82→0 치환, 10~15자리 검증
       ├─ _create_phone_code()       6자리 난수 → sha256(pepper:phone:purpose:code) 저장
       ├─ _consume_valid_code()      해시 대조 + 미소비 + 미만료 → consumed_at 기록
       └─ _create_session()          token_urlsafe(48), TTL 30일
  ← ValueError → HTTPException(400, detail=str(e))
```

### S3 (`/api/s3/*`)

```
api/file_upload_api.py  →  services/s3_service.py:S3Service
                              └─ boto3.client(endpoint_url=DOMAIN, region_name=REGION, ...)
```

`S3Service`는 `upload_file`, `upload_fileobj`, `delete_file`, `delete_prefix`, `file_exists`, `upload_directory`, `get_presigned_url`, `list_buckets`, `list_objects` 메서드를 제공합니다. NCP Object Storage(S3 호환)를 대상으로 합니다.

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
| `users` | `id`, `phone_number`(unique), `is_phone_verified`, `created_at`, `updated_at` | |
| `phone_verification_codes` | `id`, `phone_number`, `purpose`(`signup`/`login`), `code_hash`, `expires_at`, `consumed_at`, `created_at` | 평문 코드 미저장 |
| `auth_sessions` | `id`, `user_id`(FK), `token`(unique), `expires_at`, `revoked_at`, `created_at` | |
| `user_profiles` `user_goals` `meal_logs` `meal_items` `weight_logs` `food_nutrition` | `docs/DATA_MODEL.md` 3장 | 리비전 0002. `food_nutrition`은 0007에서 `sugar_g`·`sodium_mg`·`potassium_mg`·`phosphorus_mg`·`food_group` 추가 (식약처 실측, 12장). 적재는 `scripts/import_mfds_food.py` |
| `user_consents` | `id`, `user_id`(FK), `kind`, `version`, `agreed_at`, `revoked_at` | 재동의는 새 행 (이력 보존). 리비전 0003 |
| `user_health_profiles` | `id`, `user_id`(FK, unique), `blood_type`, `rh`, `deleted_at` | 민감정보. 동의 철회 시 **물리 삭제** |
| `user_conditions` | `id`, `user_id`(FK), `condition` — `(user_id, condition)` unique | 〃 |
| `user_allergies` | `id`, `user_id`(FK), `allergen`, `severity` — `(user_id, allergen)` unique | 〃 |
| `groups` | `id`, `owner_id`(FK), `name`, `kind`, `invite_code`(unique, 서버 생성) | 리비전 0004. API 계약은 `docs/DATA_MODEL.md` 9장 |
| `group_members` | `id`, `group_id`(FK), `user_id`(FK), `role` — `(group_id, user_id)` unique | 〃 |
| `pets` | `id`, `owner_id`(FK), `name`, `species`, `breed`, `birth_year`, `weight_kg`, `is_neutered`, `deleted_at` | 보호자 1:N, soft delete |
| `group_pets` | `id`, `group_id`(FK), `pet_id`(FK) — `(group_id, pet_id)` unique | 사람 멤버와 테이블 분리 (다형성 FK 회피) |
| `pet_feeding_logs` | `id`, `pet_id`(FK), `fed_at`, `food_label`, `amount_g`, `kcal`(nullable) | 칼로리 산출(RER/MER)은 다음 단계 |
| `diet_recommendations` | `id`, `user_id`(FK), `rec_date`, `meal_type`, `items`(JSONB), `excluded`(JSONB), `source` — `(user_id, rec_date, meal_type)` unique | 리비전 0006. 추천 캐시. 계약은 `docs/DATA_MODEL.md` 11장, 후보 생성·선정은 12·13장 (순수 규칙, `source` 항상 `rule`) |

- 스키마 변경은 **Alembic 리비전으로만** 합니다 (`alembic/versions/`). `create_all`은 신규 테이블 생성용으로만 남아 있습니다.
- 세션 토큰 검증은 `api/dependencies.py:get_current_user`가 담당합니다. 단 `/api/predict`, `/api/gpt-predict`, `/api/s3/*`는 여전히 무인증 공개입니다.
- `/api/me/health-profile`·`/api/me/conditions`·`/api/me/allergies`는 유효한 `sensitive_health` 동의(최신 행의 `revoked_at IS NULL`)가 없으면 **403**을 반환합니다. 401(미로그인)과 구분됩니다.

## 전역 초기화 (import 시점)

| 모듈 | 부작용 | 실패 조건 |
|------|--------|-----------|
| `services/predict_service.py:22` | `YOLO("runs/classify/.../last.pt")` 로드 | cwd가 저장소 루트가 아니면 실패 |
| `services/gpt_oss_service.py:15` | `load_dotenv()` — **cwd 기준으로 `.env` 탐색** | — |
| `services/gpt_oss_service.py:24` | `InferenceClient(api_key=os.environ["HF_TOKEN"])` | `.env`와 셸 환경변수 **양쪽 모두에** `HF_TOKEN`이 없으면 `KeyError` |
| `services/s3_service.py:11` | `load_dotenv()` | — |
| `api/predict_api.py:11` | `setup_level_logger(INFO)` → `task-logs/` 디렉토리 생성 | — |

이 때문에 `import main`만 해도 모델 로드·`.env` 탐색·토큰 조회가 일어납니다. 테스트를 도입하려면 지연 로딩이 선행되어야 합니다.

두 부작용이 모두 **cwd에 묶여 있다**는 점이 중요합니다. 저장소 루트가 아닌 곳에서 실행하면 가중치도, `.env`도 찾지 못합니다.

## 로깅 규칙

`setup_level_logger(level)`는 `LevelFilter`로 **해당 레벨만** 기록합니다. 따라서 레벨마다 로거를 따로 만들어야 합니다.

```python
info_logger  = setup_level_logger(logging.INFO)    # → task-logs/info_log.txt
error_logger = setup_level_logger(logging.ERROR)   # → task-logs/error_log.txt
```

**INFO 로거로 `.error()`를 호출하면 레코드가 소멸합니다.** `api/predict_api.py`와 `api/file_upload_api.py`가 이 버그를 갖고 있었고, 두 파일 모두 `error_logger`를 추가해 고쳤습니다.

실측: 비이미지 업로드 → `error_log.txt`에 `UnidentifiedImageError` 기록, `info_log.txt`에는 ERROR 라인 0개, 응답 본문에는 내부 예외 미노출.

## 로깅

`log_utils.setup_level_logger(level)`는 **레벨당 하나의 로거**를 만들고, `LevelFilter`로 그 레벨만 통과시킵니다.

```
task-logs/info_log.txt    ← INFO 만
task-logs/error_log.txt   ← ERROR 만 (setup_level_logger(ERROR) 호출 시)
```

- `RotatingFileHandler(maxBytes=1MB, backupCount=5)`
- 콘솔 핸들러도 함께 붙습니다
- 현재 `api/predict_api.py`만 사용합니다. 다른 라우터는 로깅하지 않습니다.

## 애플리케이션 수명주기

| 시점 | 동작 | 위치 |
|------|------|------|
| import | CORS 오리진 파싱, YOLO 로드, HF 클라이언트 생성, 로거 생성 | `main.py`, `services/*` |
| startup | `init_db()` → `create_all` | `main.py:34` (`@app.on_event`, **deprecated**) |
| 요청마다 | `get_db()`가 세션 yield → finally close | `database.py:21` |

## 외부 시스템

| 시스템 | 용도 | 접점 |
|--------|------|------|
| PostgreSQL 16 | 사용자·인증코드·세션 | `database.py`, `docker-compose.yml` |
| Hugging Face Inference (provider `groq`) | `openai/gpt-oss-120b` 텍스트 생성 | `services/gpt_oss_service.py` |
| NCP Object Storage | 데이터셋·이미지 저장 | `services/s3_service.py` |
| NCP 서버 | 운영 배포 대상 | `.github/workflows/deploy.yml` |

## 배포 파이프라인

`.github/workflows/deploy.yml`

```
push → dev 브랜치
  └─ ubuntu-latest
       ├─ actions/checkout@v3
       ├─ NCP_SSH_KEY 를 ~/private-key.pem 으로 저장 (chmod 600)
       ├─ ssh-keyscan NCP_SERVER_IP >> known_hosts
       ├─ scp -r ./*  →  $PROJECT_PATH        # 저장소 전체 복사 (runs/ 70MB 포함)
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
| 무중단 배포 아님 | `pkill` → `pip install` → 기동. YOLO 로드 시간만큼 다운타임 |
| 매 배포마다 70MB 전송 | `scp -r ./*`가 `runs/`를 통째로 복사 |
| 원격 `.env` 관리 부재 | 워크플로가 환경변수를 전달하지 않습니다. 서버에 `.env`가 없으면 `HF_TOKEN` KeyError로 기동 실패 |
| 원격 Python 버전 미고정 | `python3 -m venv` — 서버의 기본 python3에 의존 |
| 불필요한 step | `- name: Deploy to NCP Server`가 실제로는 `actions/checkout@v3`를 한 번 더 실행합니다 |

<!-- TODO: 확인 필요 - NCP 서버의 .env 배치 경로와 프로세스 관리 방식(systemd 등)을 확인하지 못했습니다. -->
