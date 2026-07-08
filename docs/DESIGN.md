# DESIGN

## 설계 원칙

1. **앱이 소비하기 쉬운 계약이 모델 내부 표현보다 우선한다.** 추론 결과는 `{ label, score }`로 정규화해서 반환합니다.
2. **API 계약은 모델 교체보다 오래 산다.** 모델을 바꿔도 응답 스키마는 유지합니다.
3. **레이어는 한 방향으로만 의존한다.** `api → services → models`.
4. **실패도 계약이다.** 성공 응답만큼 실패 응답 형태를 고정합니다.
5. **비밀은 코드에 없다.** pepper, 토큰, DB 자격증명은 환경변수로만 주입합니다.

## 코드에서 확인된 설계 결정

| 결정 | 위치 | 이유 |
|------|------|------|
| 인증번호를 평문으로 저장하지 않고 pepper + sha256 해시로 저장 | `services/auth_service.py:137` | DB 유출 시 코드 재사용 방지 |
| 인증번호를 `consumed_at`으로 1회용 처리 | `services/auth_service.py:125` | 재사용 공격 차단 |
| 세션 토큰을 `secrets.token_urlsafe(48)`로 생성 | `services/auth_service.py:132` | JWT 대신 불투명 토큰 → 서버측 폐기(`revoked_at`) 가능 |
| `signup`/`login`을 `purpose` 컬럼으로 구분하고 해시 입력에 포함 | `services/auth_service.py:138` | 가입용 코드로 로그인하는 교차 사용 차단 |
| 휴대폰 번호를 저장 전 정규화 | `services/auth_service.py:19` | `010-1234-5678`, `+82 10...`을 동일 키로 취급 |
| 서비스는 `ValueError`를 던지고 api가 `HTTPException`으로 변환 | `api/auth_api.py:36` | 서비스 레이어가 HTTP를 모르게 유지 |
| Pydantic `response_model`로 응답 직렬화 | `api/auth_api.py:24` | ORM 객체 유출 방지, OpenAPI 자동 생성 |
| `AuthUser.model_config = {"from_attributes": True}` | `schemas/auth_schema.py:26` | ORM → 스키마 자동 변환 |

## 의도적으로 하지 않은 것

- **JWT를 쓰지 않습니다.** 불투명 세션 토큰 + DB 조회 방식입니다. 무상태 확장보다 즉시 폐기 가능성을 택했습니다.
- **비밀번호가 없습니다.** 휴대폰 번호 + 일회용 코드가 유일한 인증 수단입니다.
- **`/predict`에 인증을 걸지 않았습니다.** 현재 공개 엔드포인트입니다.

## 미완성 설계 (구현 전 반드시 확인)

| 항목 | 현재 상태 | 필요한 결정 |
|------|-----------|-------------|
| 세션 토큰 검증 | `AuthSession.token`을 발급만 하고 **검증하는 코드가 없음** | 인증 의존성(`Depends(get_current_user)`)을 어디에 둘지 |
| 로그아웃 | `revoked_at` 컬럼만 존재, 갱신 코드 없음 | `POST /api/auth/logout` 추가 여부 |
| 코드 발급 rate limit | 무제한 발급 가능 | 번호당 발급 횟수/간격 제한 |
| SMS 발송 | 없음. `dev_code`로 응답에 노출 | 실제 발송 연동 시점 |
| DB 마이그레이션 | `create_all`만 사용 | Alembic 도입 여부 |
| 추론 결과 저장 | 없음 | 이미지 보관 정책 (`docs/PROJECT_PLANNING.md` 참조) |

## 새 엔드포인트 추가 절차

1. `schemas/<domain>_schema.py`에 요청/응답 모델을 정의합니다. 이것이 계약의 단일 기준입니다.
2. `services/<domain>_service.py`에 로직을 작성합니다. FastAPI를 import 하지 않습니다. 실패는 `ValueError`로 던집니다.
3. `api/<domain>_api.py`에 `APIRouter`를 만들고 라우트를 추가합니다.
   - `response_model`과 `responses={400: {"model": AuthError}}`를 반드시 지정합니다.
   - `db: Session = Depends(get_db)`로 세션을 주입받습니다.
   - `try/except ValueError` → `raise HTTPException(...) from error`.
4. `api/__init__.py`에 라우터를 재수출합니다.
5. `main.py`에서 `app.include_router(<domain>_router, prefix="/api", tags=["<Domain>"])`.
6. ORM이 필요하면 `models/<domain>_model.py`에 추가하고 `database.init_db()`의 import 목록에 넣습니다.
7. `k-calAI-RN/services/`에 대응 클라이언트를 추가하고 경로가 일치하는지 확인합니다.

### 새 라우트는 반드시 `/api` prefix 아래에 둡니다

`main.py:46`의 `/predict`는 prefix 없이 루트에 붙어 있어 앱이 기대하는 `/api/predict`와 어긋납니다. 이 패턴을 복제하지 마세요. 신규 라우트는 `include_router(..., prefix="/api")`를 경유합니다.

## 응답 계약 규칙

### 성공

`response_model`로 선언된 Pydantic 모델만 반환합니다.

```python
@router.post("/auth/login/verify", response_model=AuthTokenResponse)
def verify_login(...):
    return {"access_token": ..., "expires_at": ..., "user": user}
```

### 실패

FastAPI 기본 형태인 `{"detail": "..."}`를 유지합니다. `AuthError` 스키마가 이를 문서화합니다.

```python
raise HTTPException(status_code=400, detail="인증번호가 올바르지 않거나 만료되었습니다.") from error
```

**금지:** `main.py:58`처럼 `{"error": str(e)}`를 500으로 반환하는 형태. 앱의 `readErrorMessage`는 `detail` 키만 파싱하므로(`k-calAI-RN/services/calorie-api.ts:98`) 이 응답은 사용자에게 원시 예외 문자열로 노출됩니다. 새 코드에서 반복하지 않습니다.

### 오류 메시지

사용자에게 보일 문장은 **한국어**로, 다음 행동을 알려주는 형태로 작성합니다.

```python
raise ValueError("이미 가입된 휴대폰 번호입니다. 로그인으로 진행해주세요.")
raise ValueError("가입되지 않은 휴대폰 번호입니다. 회원가입을 먼저 진행해주세요.")
```

내부 예외(`str(e)`, 스택트레이스, 라이브러리 이름)를 그대로 담지 않습니다.

## 도메인 모델 규칙

- 시간은 **timezone-aware UTC**로 저장합니다. `datetime.now(UTC)`를 쓰고 `datetime.utcnow()`는 쓰지 않습니다 (`services/auth_service.py:5,92`).
- `created_at`/`updated_at`은 `server_default=func.now()`로 DB가 채웁니다.
- 만료 시각은 값으로 저장하고(`expires_at`), 조회 시 `expires_at > now`로 필터합니다. 애플리케이션에서 사후 계산하지 않습니다.
- "소비됨"/"폐기됨"은 삭제가 아니라 타임스탬프 컬럼(`consumed_at`, `revoked_at`)으로 표현합니다.

## 모델·추론 규칙

- 모델 내부 클래스명, 라이브러리 세부사항을 API에 노출하지 않습니다.
- 추론 결과는 앱이 바로 쓸 수 있는 필드로 가공해서 반환합니다.
- 추론 정확도 실험 코드는 서비스 코드와 분리하고, 실험 결과를 API 계약 변경의 근거로 삼지 않습니다.
- 모델 로딩 위치를 바꿀 때는 서버 시작 시간, 메모리 사용량, 첫 요청 지연을 함께 고려합니다.

## 변경 관리

- API 계약(경로, 요청 필드, 응답 모델)이 바뀌면 **서버 내부 리팩터링이 아니라 breaking change**입니다.
- 계약 변경은 `k-calAI-RN`의 영향 범위를 함께 확인한 뒤에만 머지합니다.
- 모델 성능 작업과 제품 API 안정화 작업을 같은 변경에 섞지 않습니다.
