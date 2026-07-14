# DESIGN

## 설계 원칙

1. **앱이 소비하기 쉬운 계약이 모델 내부 표현보다 우선한다.** 추론 결과는 `{ label, score }`로 정규화해서 반환합니다.
2. **API 계약은 모델 교체보다 오래 산다.** YOLO 가중치를 바꿔도 응답 스키마는 유지합니다.
3. **레이어는 한 방향으로만 의존한다.** `api → services → models`.
4. **실패도 계약이다.** 성공 응답만큼 실패 응답 형태를 고정합니다.
5. **비밀은 코드에 없다.** pepper, 카카오 client_secret·어드민 키, Gemini 키, DB 자격증명은 환경변수로만 주입합니다. 앱 번들에는 어떤 비밀값도 넣지 않습니다.

## 코드에서 확인된 설계 결정

| 결정 | 위치 | 이유 |
|------|------|------|
| 세션 토큰·연동 코드를 `secrets.token_urlsafe`로 생성하고 **해시만 저장** | `services/auth_service.py` | JWT 대신 불투명 토큰 → 서버측 폐기(`revoked_at`) 가능. 연동 코드는 딥링크 URL에 실려 나가므로 DB 유출과 조합되면 안 된다 |
| 서비스는 `ValueError`/`RuntimeError`를 던지고 api가 HTTP로 변환 | `api/auth_api.py:36` | 서비스 레이어가 HTTP를 모르게 유지 |
| 추론을 로컬 LLM이 아닌 HF Inference API로 | `services/gpt_oss_service.py:24` | 로컬 CPU로는 20B 모델 최소사양 미달 (커밋 `4184460` 참조) |
| 이미지 분류를 `transformers` 파이프라인에서 YOLO로 교체 | `services/predict_service.py:22` | 한국 음식 150클래스 자체 학습 모델 적용 (커밋 `494eed1`) |
| YOLO 모델을 모듈 전역에 로드 | `services/predict_service.py:22` | 요청마다 로드하면 지연이 큼. 대신 서버 시작 시간과 cwd에 묶임 |
| S3 연동(`/api/s3/*` 8라우트, `S3Service`, boto3) 전면 제거 | 2026-07-12 | NCP Object Storage 자원 중단 확정. `meals.photo_s3_key` 컬럼만 선반영 유지 (`docs/DATA_MODEL.md` 4장) |
| `/api/predict`·`/api/gpt-predict`에 Bearer 인증 적용 | `api/predict_api.py` (2026-07-12) | 무인증 공개 추론 라우트 제거. `sensitive_health` 동의는 요구하지 않음 (단순 이미지 인식) |
| 요금제를 코드 enum이 아닌 **참조 테이블**(`plans`)로 | `models/subscription_model.py` (2026-07-14) | 가격·한도는 릴리즈 없이 조정돼야 하고 앱이 목록을 그린다 (10장 규칙) |
| 한도 초과를 **402**로, `PlanLimitError` 전역 핸들러 | `main.py` (2026-07-14) | 429(기다리면 풀림)와 구분. 어느 라우트든 같은 본문이라야 앱이 한 곳에서 업그레이드로 분기 |
| 비전 쿼터를 **선차감 → 실패 시 환불** | `services/subscription_service.py` (2026-07-14) | 성공 후 차감이면 동시 요청이 전부 한도를 통과한다. 판정·증가는 한 문장의 UPSERT로 원자화 |
| 쿼터 리셋만 **KST 자정** (기록은 UTC 경계 유지) | `timeutil.py` (2026-07-14) | "오늘 몇 건 남았나"는 사용자 체감값이라 국내 기준시를 따른다 |
| 인증을 **카카오 로그인 단일 수단**으로 (SMS 철회) | `services/kakao_client.py` (2026-07-14) | 인증 비용 0원. 전화번호는 로그인 식별자·그룹 표시 외에 쓰이지 않았다. **대가로 무료 티어 어뷰징 방어를 잃었다** (카카오계정은 이메일만으로 생성 가능) — 21장 |
| 카카오 **네이티브 SDK 대신 REST(서버 주도)** | `api/auth_api.py` (2026-07-14) | 커스텀 스킴은 Redirect URI 등록 불가 + `client_secret` 필수 → 토큰 교환은 서버에서. 앱·웹 빌드가 같은 코드로 동작 |
| 콜백이 **1회용 연동 코드**를 발급 | `models/auth_model.py:KakaoLinkCode` (2026-07-14) | 카카오 인가 코드는 1회용인데 신규 회원은 동의·요금제 선택을 거쳐야 한다 |
| 그룹 정원을 **소유자 요금제**로 판정 | `services/subscription_service.py` (2026-07-14) | 정원을 결제한 사람은 소유자다. 무료 회원도 Premium 그룹에는 들어올 수 있다 |

## 의도적으로 하지 않은 것

- **JWT를 쓰지 않습니다.** 불투명 세션 토큰 + DB 조회 방식입니다.
- **비밀번호가 없습니다.** 카카오 로그인이 유일한 인증 수단입니다 (2026-07-14 이전엔 휴대폰 OTP).
- **로컬 LLM을 띄우지 않습니다.** HF Inference API를 호출합니다.

## 미완성 설계 (구현 전 반드시 확인)

| 항목 | 현재 상태 | 필요한 결정 |
|------|-----------|-------------|
| ~~`/api/s3/*` 실패 응답~~ | **소멸** — S3 라우트 전체 제거 (2026-07-12) | — |
| ~~엔드포인트 인증~~ | **해결됨** — `/api/predict`·`/api/gpt-predict`에 `Depends(get_current_user)` 적용 (2026-07-12) | — |
| ~~SMS 발송~~ | **소멸** (2026-07-14) — 인증을 카카오 로그인으로 교체하며 SMS·OTP를 제거했다 (21장) | — |
| **카카오 콘솔 설정** | 코드는 완성. Redirect URI 등록·client_secret·어드민 키가 없으면 실제 로그인이 안 된다 | **사용자 작업** (developers.kakao.com) |
| 카카오 연결 해제 웹훅 | 사용자가 카카오에서 직접 연결을 끊으면 우리 DB가 모른다 | 웹훅 수신 라우트 추가 여부 |
| **요금제 결제 연동** | `PUT /api/me/subscription`이 **검증 없이** 플랜을 바꾼다 — 누구나 Premium이 된다 | 인앱결제(App Store / Play Billing) 영수증 검증. **이 상태로 운영 배포 불가** (20장) |
| 칼로리 프롬프트 | **앱에 하드코딩** (`k-calAI-RN/services/calorie-api.ts:71`) | 서버 템플릿화 시점 |
| `runs/` 70MB | 저장소에 커밋됨 | 외부 스토리지 이전 (S3 연동은 제거됨 — 대안 스토리지 결정 필요) |
| 라벨 표시명 | YOLO가 한국어 클래스명을 그대로 반환 | 사용자 친화 표시명 매핑이 필요한지 |

## 새 엔드포인트 추가 절차

1. `schemas/<domain>_schema.py`에 요청/응답 모델을 정의합니다. 이것이 계약의 단일 기준입니다.
2. `services/<domain>_service.py`에 로직을 작성합니다. FastAPI를 import 하지 않습니다.
3. `api/<domain>_api.py`에 `APIRouter`를 만들고 라우트를 추가합니다.
   - `response_model`과 `responses={...}`를 지정합니다.
   - DB가 필요하면 `db: Session = Depends(get_db)`.
   - **예외를 `return`하지 말고 `raise HTTPException(...)` 하세요.** `response_model`이 걸려 있으면 다른 형태의 `return`은 500으로 바뀝니다 (`api/predict_api.py:27`의 버그).
4. `api/__init__.py`에 라우터를 재수출합니다.
5. `main.py`에서 `app.include_router(<domain>_router, prefix="/api", tags=["<Domain>"])`.
6. ORM이 필요하면 `models/<domain>_model.py`에 추가하고 `database.init_db()`의 import 목록에 넣습니다.
7. 새 환경변수는 **`.env.example`에 반드시 추가**합니다.
8. `k-calAI-RN/services/`에 대응 클라이언트를 추가하고 경로가 일치하는지 확인합니다.

## 응답 계약 규칙

### 성공

`response_model`로 선언된 Pydantic 모델과 **정확히 일치하는** 형태만 반환합니다.

```python
@router.post("/predict", response_model=PredictionResponse)
async def predict(file: UploadFile = File(...)):
    return {"predictions": predict_image(await file.read())}
```

### 실패

FastAPI 기본 형태인 `{"detail": "..."}`를 유지합니다.

```python
raise HTTPException(status_code=400, detail="인증번호가 올바르지 않거나 만료되었습니다.")
```

`api/predict_api.py`가 표준 형태입니다. 내부 예외는 로그에만 남기고, 클라이언트에는 사용자용 한국어 메시지를 줍니다.

```python
except Exception as e:
    error_logger.error(f"predict 실패 {file.filename}: {e!r}")
    raise HTTPException(
        status_code=500,
        detail="이미지 분석에 실패했습니다. 다른 사진으로 다시 시도해주세요.",
    ) from e
```

**두 가지를 하지 마세요.**

```python
# response_model 이 걸린 라우트에서 다른 형태를 return → 검증 실패 → 500 평문
except Exception as e:
    return {"error": str(e)}

# 내부 예외 메시지를 그대로 노출 (삭제된 api/file_upload_api.py 에 있던 안티패턴)
raise HTTPException(status_code=500, detail=f"파일 업로드 실패: {str(e)}")
```

앱의 `readErrorMessage`는 `detail` 키만 파싱합니다 (`k-calAI-RN/services/calorie-api.ts:98`). `{"error": ...}`나 평문 응답은 사용자에게 원시 문자열로 노출됩니다.

### 오류 메시지

사용자에게 보일 문장은 **한국어**로, 다음 행동을 알려주는 형태로 작성합니다.

```python
raise ValueError("이미 가입된 카카오 계정입니다. 로그인으로 진행해주세요.")
```

내부 예외(`str(e)`, 스택트레이스, 라이브러리 이름, 외부 SDK 오류코드)를 그대로 담지 않습니다.

## 도메인 모델 규칙

- **사용자 선택지의 관리 기준** (2026-07-09 확정): 선택지가 서비스 로직의 데이터와 조인되거나 릴리즈 없이 늘어나야 하면 **참조 테이블**(`condition_types`, `allergen_types` — `docs/DATA_MODEL.md` 10장)로 관리하고 `GET /api/meta/options`로 내려줍니다. 화면 구조·계산식 자체에 붙어 있는 값(끼니 4종, 혈액형, 섭취량 프리셋)은 코드 enum을 유지합니다. 참조 테이블 값 검증은 Pydantic `Literal`이 아니라 서비스 레이어의 테이블 조회로 합니다.
- 시간은 **timezone-aware UTC**로 저장합니다. `datetime.now(UTC)`를 쓰고 `datetime.utcnow()`는 쓰지 않습니다.
- `created_at`/`updated_at`은 `server_default=func.now()`로 DB가 채웁니다.
- 만료는 `expires_at` 값으로 저장하고 조회 시 `expires_at > now`로 필터합니다.
- "소비됨"/"폐기됨"은 삭제가 아니라 타임스탬프 컬럼(`consumed_at`, `revoked_at`)으로 표현합니다.

## 모델·추론 규칙

- 모델 내부 클래스명, 라이브러리 세부사항을 API에 노출하지 않습니다.
- 추론 결과는 `Prediction(label, score)` 상위 3개로 정규화해 반환합니다.
- **가중치 경로를 바꿀 때는 `services/predict_service.py` 한 곳만 고칩니다.** 라우터나 스키마가 경로를 알면 안 됩니다.
- 모델 로딩 위치를 바꿀 때는 서버 시작 시간, 메모리, 첫 요청 지연, **cwd 의존성**을 함께 고려합니다.
- 추론 실험 코드(`yolo_test.py` 등)는 `.gitignore`에 있습니다. 제품 코드와 섞지 않습니다.

## 변경 관리

- API 계약(경로, 요청 필드, 응답 모델)이 바뀌면 **서버 내부 리팩터링이 아니라 breaking change**입니다.
- 계약 변경은 `k-calAI-RN`의 영향 범위를 함께 확인한 뒤에만 머지합니다.
- 모델 성능 작업과 제품 API 안정화 작업을 같은 변경에 섞지 않습니다.
- `dev` 브랜치 push는 **즉시 배포를 트리거**합니다. 실험 커밋을 올리지 않습니다.
