# ARCHITECTURE

## 모듈 구조

```
kcalAI-model/
├── main.py                     # 앱 생성, CORS, 라우터 등록, startup 훅
├── database.py                 # engine, SessionLocal, Base, get_db, init_db
├── log_utils.py                # 레벨별 RotatingFileHandler 로거 팩토리
├── api/
│   ├── __init__.py             # 라우터 3종 재수출
│   ├── auth_api.py             # /auth/**
│   ├── predict_api.py          # /predict, /gpt-predict
│   └── file_upload_api.py      # S3 업로드·삭제·조회 (8 라우트)
├── services/
│   ├── auth_service.py         # 인증 코드 발급/검증, 세션 생성
│   ├── predict_service.py      # YOLO 분류
│   ├── gpt_oss_service.py      # HF InferenceClient (groq) 텍스트 생성
│   └── s3_service.py           # S3Service 클래스 (boto3)
├── schemas/
│   ├── auth_schema.py
│   ├── predict_schema.py       # Prediction, PredictionResponse, ErrorResponse
│   ├── gpt_schemas.py          # GptAnswer, GptResponse, GptError
│   └── s3_schemas.py
├── models/
│   └── auth_model.py           # User, PhoneVerificationCode, AuthSession
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

## 데이터 모델

| 테이블 | 주요 컬럼 | 비고 |
|--------|-----------|------|
| `users` | `id`, `phone_number`(unique), `is_phone_verified`, `created_at`, `updated_at` | |
| `phone_verification_codes` | `id`, `phone_number`, `purpose`(`signup`/`login`), `code_hash`, `expires_at`, `consumed_at`, `created_at` | 평문 코드 미저장 |
| `auth_sessions` | `id`, `user_id`(FK), `token`(unique), `expires_at`, `revoked_at`, `created_at` | |

- 스키마 생성: `Base.metadata.create_all(bind=engine)` — **마이그레이션 도구 없음**. 컬럼 변경은 반영되지 않습니다.
- `AuthSession.token`을 검증하는 코드는 **없습니다.** `/api/predict`, `/api/s3/*` 모두 공개 엔드포인트입니다.

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
