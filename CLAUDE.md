# kcalAI-model - Knowledge Base

> 이 문서는 Claude가 프로젝트 작업 시 실수를 방지하기 위한 엄격한 기준을 제공합니다.

## 프로젝트 개요

**kcalAI-model**은 헬스케어 앱의 식단 분석 기능을 지원하는 **FastAPI 기반 AI 추론 서버**입니다. 음식 이미지 분류와 휴대폰 인증을 담당하며, `k-calAI-RN` 앱이 유일한 소비자입니다.

메인 제품이 아니라 상위 앱의 기능 서버라는 위치를 유지합니다. 자세한 제품 맥락은 `docs/SERVICE_POSITIONING.md`를 참조하세요.

### 핵심 기술 스택

| 항목 | 기술 |
|------|------|
| 프레임워크 | FastAPI 0.117.1 |
| 언어 | Python (CI: 3.12 / 로컬 확인: 3.13.5) |
| ASGI 서버 | uvicorn 0.36.0 |
| ORM | SQLAlchemy 2.0.36 (`DeclarativeBase`, `Mapped`) |
| 데이터베이스 | PostgreSQL 16 (docker-compose) |
| DB 드라이버 | psycopg2-binary 2.9.10 |
| 검증/스키마 | Pydantic 2.11.9 |
| 추론 | transformers 4.56.2 + torch 2.8.0 |
| 모델 | `nateraw/food` (HF `image-classification` 파이프라인) |
| 배포 | GitHub Actions → NCP 서버 (SSH + uvicorn) |
| 테스트 | **없음** (프레임워크 미도입) |

---

## 빌드 및 실행 명령어

```bash
# 1. DB 기동 (필수 - 서버 startup 시 init_db가 연결을 시도함)
docker compose up -d postgres

# 2. 가상환경 + 의존성
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 3. 환경변수
cp .env.example .env

# 4. 서버 실행
uvicorn main:app --reload --port 8000

# 5. API 문서
open http://127.0.0.1:8000/docs
```

> `requirements.txt`는 **UTF-16 LE + BOM + CRLF** 인코딩입니다. pip는 정상 파싱하지만(확인 완료),
> 편집기·`grep`·git diff가 깨져 보입니다. 편집할 때 UTF-8로 재저장하지 말고 인코딩을 유지하거나,
> 별도 작업으로 UTF-8 변환 + 커밋하세요. 다른 작업과 섞지 않습니다.

### 검증 명령어

```bash
python -c "import main"          # import 시 모델을 즉시 다운로드/로드하므로 느립니다
```

<!-- TODO: 확인 필요 - lint/format/test 명령어가 정의되어 있지 않습니다. 도입 시 이 표를 채우세요. -->

| 목적 | 명령어 |
|------|--------|
| 테스트 | 없음 |
| 린트 | 없음 |
| 포맷 | 없음 |

---

## 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `DATABASE_URL` | `postgresql+psycopg2://kcal:kcal@localhost:5432/kcal` | `database.py` |
| `AUTH_CODE_TTL_MINUTES` | `5` | 인증번호 유효 시간 |
| `AUTH_SESSION_TTL_DAYS` | `30` | 세션 토큰 유효 기간 |
| `AUTH_CODE_PEPPER` | `development-only-pepper` | 코드 해시 pepper. **운영에서 반드시 교체** |
| `AUTH_INCLUDE_DEV_CODE` | `true` | 응답에 인증번호를 그대로 노출. **운영에서 반드시 `false`** |
| `CORS_ALLOW_ORIGINS` | localhost:3000,5173 | `main.py`에서 읽지만 `.env.example`에 **누락** |
| `HF_TOKEN` | (빈값) | `.env.example`에 있으나 현재 코드에서 **미사용** |

---

## 현재 실제 API (코드 기준)

| 메서드 | 경로 | 정의 위치 |
|--------|------|-----------|
| `POST` | `/predict` | `main.py:46` |
| `POST` | `/api/auth/signup/request-code` | `api/auth_api.py:22` |
| `POST` | `/api/auth/signup/verify` | `api/auth_api.py:39` |
| `POST` | `/api/auth/login/request-code` | `api/auth_api.py:56` |
| `POST` | `/api/auth/login/verify` | `api/auth_api.py:73` |

---

## 알려진 불일치 (작업 전 반드시 인지)

이 항목들은 **문서·클라이언트가 코드보다 앞서 있는 상태**입니다. 임의로 문서를 코드에 맞추거나 코드를 문서에 맞추지 말고, 어느 쪽이 정답인지 사용자에게 확인한 뒤 진행하세요.

| # | 내용 | 근거 |
|---|------|------|
| 1 | 앱은 `/api/predict`를 호출하지만 서버는 `/predict`로 노출 → **404** | `main.py:46` vs `k-calAI-RN/services/calorie-api.ts:15` |
| 2 | 앱이 호출하는 `/api/gpt-predict`가 **서버에 존재하지 않음** → 칼로리 계산 기능 동작 불가 | `k-calAI-RN/services/calorie-api.ts:19`, 서버 라우트 전수 확인 |
| 3 | `docs/PROJECT_PLANNING.md`가 `/api/s3/*`, YOLO, HF Inference API를 "현재 기능"으로 기술하지만 **코드에 없음** | `grep -rn 's3\|yolo\|InferenceClient' → 0 hits` |
| 4 | `HF_TOKEN`이 `.env.example`에 있으나 코드에서 읽지 않음 | `grep HF_TOKEN → 0 hits` |

---

## 절대 하지 말아야 할 것

- **`/api/predict`, `/api/gpt-predict`가 이미 있다고 가정하지 않는다.** 위 불일치 표를 먼저 읽습니다.
- **`AUTH_INCLUDE_DEV_CODE`를 운영에서 `true`로 두지 않는다.** 기본값이 `true`이므로 환경변수를 **설정하지 않으면 인증번호가 API 응답에 그대로 노출**됩니다 (`services/auth_service.py:16,104`).
- **`AUTH_CODE_PEPPER` 기본값을 그대로 배포하지 않는다** (`services/auth_service.py:15`).
- **`.env`를 커밋하지 않는다.** `.gitignore`에 있으나 `git add -f`로 우회하지 않습니다.
- **예외 메시지를 그대로 클라이언트에 반환하지 않는다.** `main.py:58`의 `str(e)` 노출은 기존 문제이며, 새 코드에서 반복하지 않습니다.
- **`api` 레이어에 비즈니스 로직을 넣지 않는다.** HTTP 입출력과 `ValueError → HTTPException(400)` 변환만 담당합니다.
- **DB 스키마를 변경할 때 마이그레이션 없이 진행하지 않는다.** 현재 `Base.metadata.create_all`만 사용하므로 **기존 컬럼 변경이 반영되지 않습니다** (`database.py:32`).
- **모델 성능 실험과 제품 API 안정화를 같은 커밋에 섞지 않는다** (`docs/PROJECT_CONVENTIONS.md`).
- **API 계약을 바꾸면서 `k-calAI-RN`을 함께 확인하지 않고 끝내지 않는다.**

---

## docs 인덱스

| 작업 | 먼저 읽을 문서 |
|------|----------------|
| 모듈 구조·의존성 파악 | `docs/ARCHITECTURE.md` |
| 새 엔드포인트/스키마 추가 | `docs/DESIGN.md` → `docs/ARCHITECTURE.md` |
| 코드 작성 직전 | `docs/CODE_STYLE.md` |
| 리뷰·머지 전 | `docs/REVIEW.md` |
| 서브에이전트 실행 | `docs/SUBAGENTS.md` |
| 제품 맥락·API 책임 범위 | `docs/PROJECT_PLANNING.md`, `docs/SERVICE_POSITIONING.md` |
| 세션 운영·변경 관리 규칙 | `docs/PROJECT_CONVENTIONS.md` |

---

## 연관 저장소

`k-calAI-RN` (Expo/React Native 앱) — 이 서버의 유일한 소비자입니다.
API 계약 변경은 두 저장소를 **같은 작업 단위**에서 수정합니다.
