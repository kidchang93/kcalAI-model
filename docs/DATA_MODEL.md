# DATA MODEL — 헬스케어 확장 (확정)

> 상태: **확정**. 2026-07-09 세션에서 열린 결정 6건을 닫고 코드 실측으로 검증했다.
> Figma 기획안: https://www.figma.com/design/3d0NExBqJoQLyw8qcEetwH

## 1. 확정한 결정

| 결정 항목 | 선택 | 근거 |
|---|---|---|
| 사진 원본 저장 | **저장하지 않음.** 단 `photo_s3_key` 컬럼은 미리 둔다 | 개인정보 최소수집. 그러나 마이그레이션 도구가 없어 컬럼 후추가가 불가능하다 |
| 목표 칼로리 산출식 | Mifflin-St Jeor + 활동계수 | 프로필 입력값(성별·생년·키·몸무게·활동량)과 정확히 일치한다 |
| 운동·물 섭취 기록 | 첫 릴리즈 제외 | 핵심 루프만 완성한다 |
| 다크모드 | 라이트 전용 | 실화면 3개가 색을 하드코딩 중이라 작업량이 두 배가 된다 |
| 웹 정식 지원 | **지원** (2026-07-09 변경) | 웹으로도 쓰고 있다. 네이티브 전용 API를 쓰지 않고, 화면은 중앙 정렬 max-width 컨테이너로 감싼다 |
| **칼로리 숫자 확보 (신규)** | `POST /api/nutrition/estimate` + `food_nutrition` 캐시 | 현재 `/api/gpt-predict`는 서술 문자열이라 진행률 링을 그릴 수 없다 |

### 마지막 결정이 왜 필요한가

`services/calorie-api.ts:83`이 서버 응답을 `typeof === 'string'`으로 검증한 뒤 그대로 화면에 뿌린다. **숫자 kcal이 어디에도 없다.** 따라서:

- 홈의 진행률 링(`오늘 1,340 / 2,100 kcal`)을 그릴 수 없다.
- `meal_items.kcal`에 넣을 값이 없다.

`POST /api/nutrition/estimate`는 LLM에 **JSON 스키마를 강제**해 구조화된 값을 받는다. 같은 `food_label` 재요청은 `food_nutrition`에서 돌려줘 **HF Inference API 토큰 소비를 막는다.**

---

## 2. 설계 제약 (코드 실측)

작업 전에 반드시 인지한다. 근거는 실제 파일:줄이다.

| # | 제약 | 근거 |
|---|------|------|
| 1 | **PK/FK는 전부 `int` 자동증가.** UUID는 관례 이탈이다 | `models/auth_model.py:12,42` |
| 2 | 모든 시간 컬럼이 `DateTime(timezone=True)` + `server_default=func.now()` | `auth_model.py` 3개 테이블 전부 |
| 3 | 코드에서 시간은 `datetime.now(UTC)`를 쓴다. `utcnow()` 금지 | `services/auth_service.py:92,108,133` |
| 4 | 삭제·폐기·소비는 **nullable 타임스탬프**로 표현한다 (`revoked_at`, `consumed_at`) | `auth_model.py:34,45` |
| 5 | **`Base.metadata.create_all`은 기존 테이블의 컬럼 추가를 반영하지 않는다** | `database.py:32` |
| 6 | 새 `models/<domain>_model.py`는 `init_db()`의 지연 import 목록에 **반드시 추가**해야 `create_all` 대상이 된다 | `database.py:29-32` |
| 7 | **세션 토큰 검증 코드가 전무하다.** `select(AuthSession)` 0건, `get_current_user`/`Authorization`/`Bearer` 0건 | `api/` 전수 grep |
| 8 | 신규 Pydantic 스키마는 `auth_schema.py` 패턴을 따른다 (`str | None`, `XxxRequest`/`XxxResponse`) | `schemas/auth_schema.py:17,26` |

> 5번 때문에 `photo_s3_key`를 지금 넣는다. 6번 때문에 `database.py`는 **순차 편집 파일**이다.
> 7번 때문에 **인증이 모든 신규 API의 선행 과제**다. 이게 없으면 "현재 사용자"를 식별할 수 없다.

---

## 3. 신규 테이블 6개

관례: `id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)`, `created_at`은 `server_default=func.now()`, 변경되는 엔티티는 `updated_at`에 `onupdate=func.now()`를 붙인다 (`users` 패턴).

### `user_profiles` — 신체 정보

| 컬럼 | 타입 | 제약 |
|---|---|---|
| `id` | `Integer` | PK |
| `user_id` | `Integer` | FK→`users.id`, **unique** (1:1) |
| `sex` | `String(10)` | `male` / `female` |
| `birth_year` | `Integer` | 나이 대신 생년 (매년 갱신 불필요) |
| `height_cm` | `Numeric(5,1)` | |
| `weight_kg` | `Numeric(5,1)` | 최신값 캐시. 단일 진실은 `weight_logs` |
| `activity_level` | `String(20)` | `sedentary`/`light`/`moderate`/`active`/`very_active` |
| `created_at` / `updated_at` | `DateTime(tz=True)` | |

### `user_goals` — 목표

| 컬럼 | 타입 | 제약 |
|---|---|---|
| `id` | `Integer` | PK |
| `user_id` | `Integer` | FK→`users.id`, index |
| `goal_type` | `String(10)` | `loss` / `maintain` / `gain` |
| `target_kcal` | `Integer` | Mifflin-St Jeor 산출값. 사용자가 덮어쓸 수 있다 |
| `target_weight_kg` | `Numeric(5,1)` | nullable |
| `started_at` | `DateTime(tz=True)` | |
| `ended_at` | `DateTime(tz=True)` | **nullable.** 목표 변경 시 이전 행을 닫는다 (이력 보존) |

### `meal_logs` — 끼니

| 컬럼 | 타입 | 제약 |
|---|---|---|
| `id` | `Integer` | PK |
| `user_id` | `Integer` | FK→`users.id`, index |
| `logged_at` | `DateTime(tz=True)` | index. 날짜별 조회 |
| `meal_type` | `String(10)` | `breakfast`/`lunch`/`dinner`/`snack` |
| `photo_s3_key` | `String(255)` | **nullable. 첫 릴리즈는 항상 NULL** (제약 5번 때문에 선반영) |
| `total_kcal` | `Integer` | `meal_items` 합계의 **캐시**. 단일 진실은 `meal_items` |
| `deleted_at` | `DateTime(tz=True)` | nullable. soft delete |
| `created_at` / `updated_at` | `DateTime(tz=True)` | |

### `meal_items` — 끼니 안의 음식

| 컬럼 | 타입 | 제약 |
|---|---|---|
| `id` | `Integer` | PK |
| `meal_log_id` | `Integer` | FK→`meal_logs.id`, index |
| `food_label` | `String(100)` | 한국어 라벨 (YOLO 출력 또는 사용자 수정) |
| `serving_ratio` | `Numeric(4,2)` | `0.5` / `1.0` / `1.5` … |
| `kcal` | `Integer` | `serving_ratio × food_nutrition.kcal_per_serving` |
| `source` | `String(10)` | `ai` / `manual`. **모델 개선의 근거가 된다** |
| `confidence` | `Numeric(4,3)` | nullable. `source='ai'`일 때 YOLO score |
| `created_at` | `DateTime(tz=True)` | |

### `weight_logs` — 체중 추이

| 컬럼 | 타입 | 제약 |
|---|---|---|
| `id` | `Integer` | PK |
| `user_id` | `Integer` | FK→`users.id`, index |
| `measured_at` | `DateTime(tz=True)` | index |
| `weight_kg` | `Numeric(5,1)` | |
| `created_at` | `DateTime(tz=True)` | |

### `food_nutrition` ★신규 — LLM 응답 캐시

| 컬럼 | 타입 | 제약 |
|---|---|---|
| `id` | `Integer` | PK |
| `food_label` | `String(100)` | **unique, index.** 조회 키 |
| `kcal_per_serving` | `Integer` | |
| `serving_desc` | `String(100)` | 예: `1인분 (약 210g)` |
| `carbs_g` / `protein_g` / `fat_g` | `Numeric(6,1)` | nullable |
| `source` | `String(20)` | `llm` / `curated` |
| `created_at` | `DateTime(tz=True)` | |

**이 테이블이 HF 토큰 소비를 막는다.** `/api/nutrition/estimate`는 캐시를 먼저 조회하고, 없을 때만 LLM을 태운다.

---

## 4. 신규 API 계약

기존 14개 라우트는 그대로 둔다. 아래는 신규분이며 **전부 `Authorization: Bearer <token>`을 요구한다.**

| 메서드 | 경로 | 역할 | 선행 조건 |
|---|---|---|---|
| `POST` | `/api/auth/logout` | `auth_sessions.revoked_at` 갱신 | `get_current_user` |
| `GET` `PUT` | `/api/me/profile` | 신체 정보 조회·수정 | `user_profiles` |
| `GET` `PUT` | `/api/me/goal` | 목표 조회·수정 (Mifflin-St Jeor 자동 산출) | `user_goals` |
| `GET` | `/api/me/summary?date=` | 홈 진행률 — 섭취/목표/끼니별 합계 | `meal_logs` 집계 |
| `POST` | `/api/nutrition/estimate` | 음식 라벨 → 구조화 kcal. **캐시 우선** | `food_nutrition` |
| `POST` `GET` | `/api/meals` | 끼니 저장 · 날짜별 조회 | `meal_logs` + `meal_items` |
| `DELETE` | `/api/meals/{id}` | soft delete (`deleted_at`) | **소유자 검증 필수** |
| `POST` `GET` | `/api/weights` | 체중 기록·추이 | `weight_logs` |

### `GET /api/me/summary` 응답 스키마 (확정)

```jsonc
{
  "date": "2026-07-09",
  "target_kcal": 2017,        // 목표 미설정 시 null. 0 이 아니다.
  "consumed_kcal": 430,
  "remaining_kcal": 1587,     // 목표 미설정 시 null
  "meals": {                  // 배열이 아니라 객체 맵. 끼니 4종은 항상 전부 존재한다
    "breakfast": 430, "lunch": 0, "dinner": 0, "snack": 0
  }
}
```

**목표 없음과 목표 0kcal은 다르다.** `target_kcal: 0`을 반환하면 앱이 "목표 설정" CTA를 띄울 수 없고 진행률이 0으로 나뉜다. 반드시 `null`이다.

`Numeric` 컬럼(`height_cm`, `weight_kg`, `serving_ratio`, `confidence`, `carbs_g`…)은 JSON에서 **float**로 직렬화된다 (실측: `70.5`, `0.91`).

### 선행 과제 — 순서를 지킨다

1. **서버**: `Depends(get_current_user)` — `auth_sessions` 조회 + `expires_at` / `revoked_at` 검사
2. **앱**: 모든 요청에 `Authorization: Bearer <access_token>` 첨부 (현재 발급만 하고 안 붙인다)
3. **앱**: `expo-secure-store`로 세션 영속화 (현재 모듈 전역 변수라 재시작하면 로그아웃)
4. **서버**: **Alembic 도입** — `create_all`로는 컬럼 추가가 반영되지 않는다

1번 없이 5~8번 엔드포인트를 만들면 **아무나 남의 신체 정보를 읽는다.**

---

## 5. 목표 칼로리 산출식 (Mifflin-St Jeor)

```
BMR(male)   = 10 × weight_kg + 6.25 × height_cm − 5 × age + 5
BMR(female) = 10 × weight_kg + 6.25 × height_cm − 5 × age − 161

TDEE = BMR × activity_factor
```

| `activity_level` | factor |
|---|---|
| `sedentary` | 1.2 |
| `light` | 1.375 |
| `moderate` | 1.55 |
| `active` | 1.725 |
| `very_active` | 1.9 |

| `goal_type` | `target_kcal` |
|---|---|
| `loss` | `TDEE − 500` (주당 약 0.45kg 감량) |
| `maintain` | `TDEE` |
| `gain` | `TDEE + 300` |

`age = 현재연도 − birth_year`. 산출값은 **기본값일 뿐이며 사용자가 수동으로 덮어쓸 수 있다.**

> 이 값은 의료적 처방이 아니다. 화면에 "AI 추정값이며 실제와 다를 수 있습니다" 고지를 유지한다.

---

## 6. v2 추가 테이블 (온보딩 · 그룹 · 연동 · 추천)

> 2026-07-09 추가. 화면 목업: `kcal/mockups/healthcare-flow.html`
> 제품 기획: `k-calAI-RN/docs/HEALTHCARE_EXPANSION.md` 9~13장
> **범위: MVP / PoC.** 의학 전문가 감수와 법률 검토는 이후 단계에서 붙는다.

Alembic이 도입됐으므로 컬럼 추가는 이제 마이그레이션으로 처리한다. `create_all`에 의존하지 않는다.

| 테이블 | 목적 | 주요 컬럼 |
|---|---|---|
| `user_consents` | **가입 시 동의 이력** | `user_id` · `kind`(`sensitive_health`/`terms`/`privacy`) · `agreed_at` · `revoked_at` · `version` |
| `user_health_profiles` | 민감정보 분리 보관 | `user_id`(FK, unique) · `blood_type` · `rh` · `deleted_at` |
| `user_conditions` | 질병 유무 (복수) | `user_id` · `condition`(`diabetes`/`pregnancy`/`ckd`/`cancer`/`hypertension`) |
| `user_allergies` | 알러지 재료 (복수) | `user_id` · `allergen` · `severity` |
| `groups` | 모임 | `owner_id` · `name` · `kind`(`family`/`couple`/`friends`/`challenge`) · `invite_code` |
| `group_members` | 사람 참여 (N:N) | `group_id` · `user_id` · `role`(`owner`/`member`) · `joined_at` |
| `pets` | **반려동물 (보호자 1 : N)** | `owner_id`(FK→`users.id`) · `name` · `species`(`dog`/`cat`/`other`) · `breed` · `birth_year` · `weight_kg` · `is_neutered` · `deleted_at` |
| `group_pets` | 그룹에 참여한 반려동물 | `group_id` · `pet_id` · `joined_at` |
| `pet_feeding_logs` | 사료 급여 기록 | `pet_id` · `fed_at` · `food_label` · `amount_g` · `kcal`(nullable) |
| `health_integrations` | 외부 헬스 앱 연결 | `user_id` · `provider`(`apple_health`/`health_connect`) · `last_synced_at` · `scopes` |
| `activity_logs` | 동기화된 활동량 | `user_id` · `date` · `steps` · `active_kcal` · `source` |
| `diet_recommendations` | 추천 이력 · 캐시 | `user_id` · `meal_type` · `items`(JSONB) · `excluded`(JSONB) · `created_at` |

### 왜 `user_profiles`에 컬럼을 더하지 않는가

혈액형·질병·알러지는 개인정보보호법상 **건강에 관한 민감정보**다. 가입 시 별도 동의(`user_consents`)를 받고, 다른 개인정보와 분리해 보관한다. 동의 이력은 **버전과 시각**을 남겨야 나중에 약관이 바뀌었을 때 누가 무엇에 동의했는지 증명할 수 있다. 파기는 `deleted_at`으로 남긴다.

**프로덕션 전 체크리스트** (MVP에서는 막지 않는다):
- `/api/predict`와 `/api/s3/*`가 무인증 공개다. 닫아야 한다.
- `user_health_profiles`의 컬럼 암호화 여부를 결정해야 한다.
- 동의 철회 시 민감정보 즉시 파기 경로가 필요하다.

### 반려동물 — 보호자 1 : N

**반려동물은 `groups.kind`가 아니라 독립 엔티티다.** 보호자(`users.id`) 한 명이 여러 마리를 가진다. 반려동물 자체는 로그인하지 않으며 메인 사용자 층이 아니다.

- 그룹에 참여시킬 때는 `group_pets`로 붙인다. 사람 멤버(`group_members`)와 테이블을 분리한다 — 다형성 FK를 피하기 위해서다.
- 급여 기록은 `meal_logs`가 아니라 `pet_feeding_logs`에 남긴다. `meal_logs.user_id`는 사람 FK다.
- **Mifflin-St Jeor는 적용되지 않는다.** 개는 RER = `70 × 체중(kg)^0.75`, MER = RER × 활동계수(중성화·연령·비만도에 따라 1.2~1.8)로 계산이 갈린다. MVP에서는 `pet_feeding_logs.kcal`을 nullable로 두고 **급여량(g)만 기록**한다. 칼로리 산출은 다음 단계다.

### 식단 추천 — MVP 범위

`HEALTHCARE_EXPANSION.md` 2장의 비목표(*"의료 진단·질병별 식단 처방을 제공하지 않는다"*)는 **MVP/PoC 동안 유보**한다. 의학 전문가가 합류해 감수하고, 법률 검토는 그 이후에 붙는다.

MVP 구현 기준:
- 알러지·질병에 해당하는 재료를 **제외**하고 남은 칼로리 안에서 후보를 고른다.
- 모든 추천 화면에 **"AI 추정값이며 의학적 조언이 아닙니다"**를 고지한다. 이 고지는 전문가 감수 전까지 제거하지 않는다.
- 추천 결과는 `diet_recommendations`에 캐시해 LLM 재호출을 막는다.

---

## 7. 사용자 층 API 계약 (v2 1차 구현분 — 확정)

> 2026-07-09 확정. 구현 범위: `user_consents` · `user_health_profiles` · `user_conditions` · `user_allergies` 4테이블과 아래 엔드포인트. 그룹·반려동물·추천은 다음 차수다.

전부 `Authorization: Bearer` 필수. 상태코드 규약:
- **401** — 미로그인 (기존과 동일)
- **403** — 로그인했지만 `sensitive_health` 동의가 없거나 철회됨. 앱은 403을 받으면 동의 화면으로 보낸다.
- 오류 본문은 `{"detail": "<한국어>"}` 유지.

| 메서드 | 경로 | 역할 | 동의 필요 |
|---|---|---|:---:|
| `GET` | `/api/me/consents` | 내 동의 이력 (최신 우선) | — |
| `POST` | `/api/me/consents` | 동의 기록. body `{kind, version}` → 201 | — |
| `POST` | `/api/me/consents/revoke` | 철회. body `{kind}` → 아래 파기 규칙 | — |
| `GET` `PUT` | `/api/me/health-profile` | 혈액형·Rh. PUT body `{blood_type?, rh?}` | ✔ |
| `GET` `PUT` | `/api/me/conditions` | 질병 목록. PUT은 **replace-all** `{conditions: string[]}` | ✔ |
| `GET` `PUT` | `/api/me/allergies` | 알러지 목록. PUT은 **replace-all** `{allergies: [{allergen, severity?}]}` | ✔ |

### 파기 규칙 — 민감정보는 soft delete가 아니다

`sensitive_health` 철회 시 `user_health_profiles` · `user_conditions` · `user_allergies` 행을 **물리 삭제**한다(파기). 동의 행 자체는 `revoked_at`을 채워 증빙으로 남긴다. 재동의하면 새 동의 행을 만들고(이력 보존) 데이터는 처음부터 다시 입력받는다.

### 값 제약

- `consents.kind`: `sensitive_health` / `terms` / `privacy`
- `blood_type`: `A` / `B` / `O` / `AB` / `unknown`, `rh`: `+` / `-` (둘 다 nullable — 모름 허용)
- `condition`: `diabetes` / `pregnancy` / `ckd` / `cancer` / `hypertension`
- `allergen`: 자유 문자열(100자), `severity`: `mild` / `severe` (nullable)
- replace-all PUT에 빈 배열 → 전체 삭제로 처리

### 온보딩 게이트 (앱)

로그인 후 `GET /api/me/profile`이 404면 온보딩 미완료로 보고 `/onboarding`으로 보낸다. 온보딩 순서는 `HEALTHCARE_EXPANSION.md` 9장: 동의(0) → 신체(1, 기존 `PUT /api/me/profile`) → 혈액형(2) → 질병(3) → 알러지(4) → 목표(5, 기존 `PUT /api/me/goal`). 0단계에서 동의하지 않으면 2~4를 건너뛴다.

---

## 8. 배포 구조 (2026-07-09 확정)

**FastAPI가 Expo 웹 빌드를 서빙하는 단일 배포 단위**로 간다.

```
kcal/build-web.sh  →  npx expo export --platform web  →  kcalAI-model/webapp/
                                                          └─ FastAPI가 정적 서빙 (/api 이외 전부)
```

- 웹 번들은 export 시점에 `EXPO_PUBLIC_*_URL`을 **상대 경로**(`/api/...`)로 받아 같은 origin을 본다. CORS가 웹에서는 사라진다. 네이티브는 기존 절대 URL 기본값 그대로다.
- `webapp/`은 빌드 산출물이므로 **커밋하지 않는다** (`.gitignore`).
- DB는 Docker Postgres 유지 (같은 VM, 추가 비용 0). 관리형 DB 이전은 실사용자 데이터가 쌓이는 시점의 결정이다.
- 스키마 변경은 계속 Alembic 리비전으로만 한다.
- **프로덕션 웹 반영은 `deploy.yml`에 export 단계가 필요하다.** 워크플로 수정은 사용자 확인 후 별도 진행.
