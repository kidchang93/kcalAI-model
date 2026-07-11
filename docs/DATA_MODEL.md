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
- `condition`: ~~`diabetes` / `pregnancy` / `ckd` / `cancer` / `hypertension`~~ → 10장의 `condition_types` 참조 테이블로 검증한다 (2026-07-09 v3)
- `allergen`: ~~자유 문자열(100자)~~ → 10장의 `allergen_types` 표준 코드로 검증한다 (2026-07-09 v3), `severity`: `mild` / `severe` (nullable)
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

---

## 9. 그룹·반려동물 API 계약 (v2 2차 구현분 — 확정)

> 2026-07-09 확정. 구현 범위: 6장의 `groups` · `group_members` · `pets` · `group_pets` · `pet_feeding_logs` 5테이블과 아래 엔드포인트 (리비전 0004). 연동·추천(`health_integrations` 이하)은 다음 차수다.

7장의 규약을 그대로 따른다:
- 전부 `Authorization: Bearer` 필수. **401** = 미로그인.
- **403** = 로그인했지만 권한 없음 (그룹 멤버가 아님).
- **404** = 리소스 없음. **반려동물은 남의 소유일 때도 404다** — 존재 자체를 숨긴다 (`meal_logs` 삭제와 같은 규칙).
- 오류 본문은 `{"detail": "<한국어>"}`.
- `Numeric` 컬럼(`weight_kg`, `amount_g`)은 JSON에서 **float**로 직렬화된다.
- 서비스 레이어 예외 → HTTP 매핑: `ValueError`→400, `PermissionError`→403, `LookupError`→404.

| 메서드 | 경로 | 역할 | 권한 |
|---|---|---|---|
| `POST` | `/api/groups` | 그룹 생성 → **201**. owner = 현재 사용자. `invite_code`는 **서버 생성** 8자(대문자·숫자, 혼동 문자 I/L/O/0/1 제외). 생성자는 `group_members`에 `role=owner`로 자동 참여한다 | 로그인 |
| `GET` | `/api/groups` | 내가 속한 그룹 목록 (`GroupSummary[]`) | 로그인 |
| `GET` | `/api/groups/{id}` | 상세 + 멤버 목록 + 참여 반려동물 목록 | **멤버만.** 아니면 403, 없는 그룹 404 |
| `POST` | `/api/groups/join` | body `{invite_code}`로 참여 → `GroupSummary`. 코드 불일치 404, 이미 멤버 400. 대소문자는 서버가 대문자로 정규화 | 로그인 |
| `POST` | `/api/groups/{id}/pets` | body `{pet_id}`로 그룹에 반려동물 참여 → **201** `{message}`. 이미 참여 400 | **그룹 멤버이면서 펫 소유자** (멤버 아님 403, 펫 없음/남의 펫 404) |
| `POST` | `/api/pets` | 등록 → **201** `PetResponse`. owner = 현재 사용자 | 로그인 |
| `GET` | `/api/pets` | 내 반려동물 목록 (`deleted_at IS NULL`) | 로그인 |
| `PUT` | `/api/pets/{id}` | 수정 (전체 교체). 없음/남의 소유 404 | **소유자만** |
| `DELETE` | `/api/pets/{id}` | soft delete (`deleted_at`) → `{message}` | **소유자만** |
| `POST` | `/api/pets/{id}/feedings` | 급여 기록 → **201**. `amount_g`(g)만 필수, `kcal`은 nullable (RER/MER 산출은 다음 단계 — 6장) | **소유자 또는 펫이 참여한 그룹의 멤버** (가족이 함께 급여를 기록한다) |
| `GET` | `/api/pets/{id}/feedings?date=YYYY-MM-DD` | 날짜별 조회. `date` 생략 시 오늘(UTC), 하루 경계는 UTC (기존 `/api/meals`와 동일) | 〃 |

### 응답 스키마 (확정)

`GroupSummary` — 생성·목록·참여가 같은 형태를 반환한다:

```jsonc
{
  "id": 1, "owner_id": 3, "name": "우리집", "kind": "family",
  "invite_code": "A7K2MPQ9",         // 멤버에게만 보인다 (목록·상세가 이미 멤버 전용)
  "role": "owner",                    // 현재 사용자의 역할
  "member_count": 2,
  "created_at": "2026-07-09T05:00:00Z"
}
```

`GET /api/groups/{id}` (`GroupDetailResponse`):

```jsonc
{
  "id": 1, "owner_id": 3, "name": "우리집", "kind": "family",
  "invite_code": "A7K2MPQ9", "created_at": "...",
  "members": [
    // 다른 멤버의 휴대폰 번호 원본은 노출하지 않는다 (개인정보 최소노출).
    { "user_id": 3, "phone_number_masked": "010****1111", "role": "owner", "joined_at": "..." }
  ],
  "pets": [
    { "pet_id": 1, "name": "콩이", "species": "dog", "joined_at": "..." }
  ]
}
```

`PetResponse`:

```jsonc
{
  "id": 1, "owner_id": 3, "name": "콩이", "species": "dog",
  "breed": "poodle",        // nullable
  "birth_year": 2021,       // nullable
  "weight_kg": 4.2,         // nullable, float
  "is_neutered": true,      // nullable (모름 허용)
  "created_at": "...", "updated_at": "..."
}
```

`FeedingResponse`:

```jsonc
{
  "id": 1, "pet_id": 1, "fed_at": "2026-07-09T08:00:00Z",
  "food_label": "로얄캐닌 미니 어덜트",
  "amount_g": 60.0,         // float
  "kcal": null,             // MVP 에서는 항상 null 이어도 된다
  "created_at": "..."
}
```

### 값 제약

- `groups.kind`: `family` / `couple` / `friends` / `challenge`
- `group_members.role`: `owner` / `member`
- `pets.species`: `dog` / `cat` / `other`, `breed` 자유 문자열(50자)
- `invite_code`: 서버 생성 8자. 클라이언트가 지정할 수 없다
- `amount_g`: `> 0` 필수, `kcal`: nullable (`>= 0`)
- 중복 방지: `(group_id, user_id)` · `(group_id, pet_id)` unique
- 펫 soft delete 후에는 그룹 상세의 `pets` 목록·급여 API에서 모두 제외된다 (`deleted_at IS NULL` 필터)

---

## 10. 선택지 참조 테이블 · 메타 API (v2 3차 — 확정)

> 2026-07-09 확정. 구현 범위: `condition_types` · `allergen_types` 2테이블(리비전 0005, 시드 포함)과 `GET /api/meta/options`. 식단 추천(`diet_recommendations`)의 선행 작업이다 — 추천의 제외 재료·식이 규칙이 이 테이블을 조인한다.

### 규칙 — 어떤 선택지를 DB로 관리하는가

**선택지가 서비스 로직의 데이터와 조인되거나 릴리즈 없이 늘어나야 하면 참조 테이블, 화면 구조·계산식 자체에 붙어 있으면 코드 enum.**

| 선택지 | 판정 | 이유 |
|---|---|---|
| 질병(condition) | **참조 테이블** | 추천의 식이 규칙 태그가 붙는다 |
| 알러지(allergen) | **참조 테이블** | 추천의 제외 재료 키워드가 붙는다. 자유 문자열은 조인 불가 |
| 끼니(meal_type) | 코드 enum 유지 | summary 계약이 4종 고정 키를 반환하는 구조적 값 |
| 섭취량 비율 | 코드 enum 유지 | UI 프리셋일 뿐, 값 자체는 자유 숫자 |
| 혈액형/Rh | 코드 enum 유지 | 보편·불변, 붙는 로직 없음 |
| 그룹 kind, 펫 species | 코드 enum 유지 | 로직이 붙는 시점에 참조 테이블로 승격 |

### 테이블

| 테이블 | 컬럼 |
|---|---|
| `condition_types` | `code` `String(30)` PK · `label_ko` `String(50)` NOT NULL · `dietary_tags` JSONB(문자열 배열) · `sort_order` `Integer` · `is_active` `Boolean` default true |
| `allergen_types` | `code` `String(30)` PK · `label_ko` `String(50)` NOT NULL · `exclude_keywords` JSONB(문자열 배열) · `sort_order` `Integer` · `is_active` `Boolean` default true |

`dietary_tags` · `exclude_keywords`는 **추천 엔진 내부용**이다. 메타 API로 노출하지 않는다.

### 시드 (0005 데이터 마이그레이션에 포함)

| condition_types.code | label_ko | dietary_tags |
|---|---|---|
| `diabetes` | 당뇨 | `["low_sugar", "low_gi"]` |
| `pregnancy` | 임신 중 | `["no_alcohol", "no_raw"]` |
| `ckd` | 신장 질환 | `["low_sodium", "low_potassium", "low_phosphorus"]` |
| `cancer` | 암 치료 중 | `["high_protein", "food_safety"]` |
| `hypertension` | 고혈압 | `["low_sodium"]` |

| allergen_types.code | label_ko | exclude_keywords |
|---|---|---|
| `peanut` | 땅콩 | `["땅콩", "피넛"]` |
| `milk` | 우유 | `["우유", "유제품", "치즈", "버터", "크림"]` |
| `shellfish` | 갑각류 | `["새우", "게", "랍스터", "갑각류"]` |
| `egg` | 계란 | `["계란", "달걀", "마요네즈"]` |
| `wheat` | 밀 | `["밀", "밀가루", "빵", "면", "파스타"]` |
| `soy` | 대두 | `["대두", "콩", "두부", "간장", "된장"]` |
| `peach` | 복숭아 | `["복숭아"]` |

### 기존 데이터 마이그레이션 (0005)

- `user_conditions.condition`에 FK(`condition_types.code`) 추가. 기존 값 5종은 코드와 동일하므로 변환 불필요.
- `user_allergies.allergen`은 지금까지 **한국어 자유 문자열**이 저장됐다. 0005에서 시드의 `label_ko → code` 역매핑으로 변환한 뒤 FK(`allergen_types.code`)를 건다. 매핑 불가 행은 **삭제**한다 (로컬 dev 데이터뿐이며, 재온보딩으로 복구 가능).

### API

| 메서드 | 경로 | 역할 |
|---|---|---|
| `GET` | `/api/meta/options` | 온보딩 선택지 목록. **Bearer 필수** (7장 규약 일관), `sensitive_health` 동의는 요구하지 않는다 — 동의 화면 다음이 질병 선택이다 |

응답 (확정 — `is_active=true`만, `sort_order` 오름차순):

```jsonc
{
  "conditions": [ { "code": "diabetes", "label": "당뇨" }, ... ],
  "allergens":  [ { "code": "peanut",   "label": "땅콩" }, ... ]
}
```

### 검증 방식 변경

- `PUT /api/me/conditions` · `PUT /api/me/allergies`의 값 검증을 Pydantic `Literal`에서 **서비스 레이어의 참조 테이블 조회**로 바꾼다. 없는 코드는 400 `{"detail": "<한국어>"}`.
- `PUT /api/me/allergies` 요청의 `allergen` 값 의미가 자유 문자열 → **표준 코드**로 바뀐다. 앱도 같은 작업 단위에서 코드 전송으로 변경한다.
- `severity`는 `mild`/`severe` `Literal` 유지 (구조적 값).

### 앱 규칙

- 온보딩 질병·알러지 화면은 진입 시 `GET /api/meta/options`를 읽어 칩을 그린다. 실패 시 **번들 폴백 상수**(시드와 동일 code/label)로 그린다 — 온보딩이 네트워크 오류로 막히면 안 된다.
- '없음' 칩은 서버 값이 아니라 앱 전용 (`replace-all PUT` 빈 배열).

---

## 11. 식단 추천 API 계약 (v2 4차 — 확정)

> 2026-07-10 확정. 6장 MVP 기준(제외 → 남은 칼로리 내 후보 · 고지 · 캐시)의 구현 계약. 고지 문구는 전문가 감수 전까지 유지한다.

### 왜 LLM 생성인가 — "LLM은 제안, 코드는 검증"

"LLM 추천은 일관성이 없다"는 우려는 두 종류로 나뉘고, 각각 결정적 장치가 담당한다:

| 우려 | 담당 | 방법 |
|---|---|---|
| 알러지·질병 제외가 매번 지켜지나 (안전) | **서버 코드** | LLM 출력의 각 항목을 `allergen_types.exclude_keywords`로 **후처리 검사**해 걸리면 탈락시킨다. 프롬프트의 제외 지시는 1차 방어일 뿐, 최종 보장은 코드다 |
| 같은 요청에 답이 바뀌나 (재현성) | **캐시** | `(user_id, rec_date, meal_type)` 단위 1회 생성 후 `diet_recommendations`에 저장. 같은 날 재조회는 항상 같은 결과. 날이 바뀌면 새 추천 — 이 가변성은 결함이 아니라 다양성이다 |
| 응답 형태가 흔들리나 | **JSON 강제** | `nutrition/estimate`와 동일 패턴 (JSON-only 프롬프트, 파싱 실패 502) |
| 메뉴 콘텐츠는 누가 만드나 | **LLM** | 규칙 기반 대안은 감수된 메뉴 풀 DB 구축이 선행돼야 해 MVP 범위를 초과한다. 감수 콘텐츠가 생기면 정적 풀로 승격을 검토한다 |

캐시가 비용 통제도 겸한다 — LLM 호출은 사용자·날짜·끼니당 최대 1회(하루 최대 4회).

### 테이블 — `diet_recommendations` 구체화 (리비전 0006)

| 컬럼 | 타입 · 제약 |
|---|---|
| `id` | PK |
| `user_id` | FK→`users.id`, NOT NULL |
| `rec_date` | `Date` NOT NULL — 클라이언트가 보낸 날짜 (summary와 동일하게 서버는 시간대 해석을 하지 않는다) |
| `meal_type` | `String` NOT NULL — 4장 `MealType` 4종과 동일 문자열 |
| `items` | JSONB — `[{"name": str, "kcal": int, "reason": str}]` (kcal은 LLM 추정값, 고지 대상) |
| `excluded` | JSONB — 반영된 제외 조건: `{"type": "allergen"\|"condition", "code", "label"}` + 후처리로 실제 탈락한 항목: `{"type": "filtered", "name", "matched_keyword"}` |
| `source` | `String(20)` default `'llm'` |
| `created_at` | server_default now |

UNIQUE(`user_id`, `rec_date`, `meal_type`).

### API

| 메서드 | 경로 | 역할 |
|---|---|---|
| `GET` | `/api/recommendations?meal_type=<4종>&date=<YYYY-MM-DD>` | 해당 날짜·끼니 추천. **Bearer + `sensitive_health` 동의 필수(403)** — 질병·알러지를 조회에 사용하므로 7장 규약을 따른다 |

동작: 캐시 조회 → 있으면 그대로 반환(`cached: true`) → 없으면 (a) 남은 칼로리 = `target_kcal - consumed`(summary와 동일 산식, 목표 미설정이면 null로 두고 일반 추천), (b) 사용자의 `condition_types.dietary_tags` · 알러지 `label_ko` 목록으로 프롬프트 구성, (c) LLM 호출(JSON 강제, 후보 3개), (d) `exclude_keywords` 후처리 필터, (e) 저장 후 반환.

응답 (확정):

```jsonc
{
  "meal_type": "lunch",
  "rec_date": "2026-07-10",
  "items": [ { "name": "...", "kcal": 520, "reason": "..." } ],
  "excluded": [ { "type": "allergen", "code": "egg", "label": "계란" } ],
  "cached": false,
  "disclaimer": "AI 추정값이며 의학적 조언이 아닙니다."
}
```

- `disclaimer`는 **서버가 내려보낸다** — 앱 하드코딩 문구가 화면마다 어긋나는 것을 막는다.
- LLM 실패·파싱 실패는 502 (estimate와 동일). 후처리 탈락으로 items가 비면 비운 채로 저장·반환한다 — 앱이 빈 상태를 그린다 (재호출로 토큰을 태우지 않는다).

> **개정 (12장):** 식약처 음식 DB 도입으로 후보 생성 방식과 폴백이 12장 기준으로 바뀐다. 응답 계약은 동일.

---

## 12. 식약처 음식 DB 도입 — 추천 grounding (v2 5차 — 확정)

> 2026-07-10 확정. 원본: `kcal/data/식품의약품안전처_통합식품영양성분정보(음식)_20260429.csv` (19,495행 · 고유 식품명 15,568 · UTF-8 BOM). 가공식품 DB(29.8만 건 xlsx)는 보류. 원본 파일은 레포에 커밋하지 않는다.

### 원본의 두 가지 함정 (임포트가 반드시 처리)

1. **영양값은 100g/100ml 기준**(`영양성분함량기준량`)이고 1인분이 아니다. 1인분 값 = 원본값 × `식품중량` ÷ 기준량. 식품중량 누락 12행은 100g 기준으로 저장하고 `serving_desc`를 `"100g당"`으로 남긴다.
2. **식품명이 유일하지 않다** (프랜차이즈 동일 메뉴가 업체별 중복, 최대 20행). 같은 이름은 식품중량이 있는 행 우선으로 1행만 선택한다.

### `food_nutrition` 확장 (리비전 0007)

추가 컬럼 (전부 nullable): `sugar_g` · `sodium_mg` · `potassium_mg` · `phosphorus_mg` (Numeric) · `food_group` (String(30), 원본 `식품대분류명`). `source`에 `'mfds'` 값 추가. 임포트는 idempotent upsert이며, **같은 라벨의 `source='llm'` 행은 mfds가 덮어쓴다** — 실측이 추정에 우선한다.

임포트 스크립트는 서버 레포 안에 두고(`scripts/` 관례 확인 후 배치), 원본 CSV 경로를 인자로 받는다.

### 추천 후보 생성 개정 — "DB가 후보, LLM은 선택·설명"

11장의 "LLM은 제안, 코드는 검증"에서 검증 축을 실측 DB로 강화한다:

1. **후보 풀 추출 (코드)** — `food_nutrition`(source='mfds')에서:
   - `meal_type` 대분류 매핑 (2026-07-10 임포트 후 `SELECT DISTINCT food_group` 25종 실측으로 확정): `breakfast/lunch/dinner` → 밥류 · 죽 및 스프류 · 국 및 탕류 · 찌개 및 전골류 · 면 및 만두류 · 구이류 · 볶음류 · 찜류 · 조림류 · 튀김류 · 전·적 및 부침류 · 생채·무침류 · 나물·숙채류 · 김치류 (14종), `snack` → 빵 및 과자류 · 음료 및 차류 · 유제품류 및 빙과류 · 과일류 (4종). 나머지 7종(장류, 양념류 · 장아찌·절임류 · 젓갈류 — 양념·소량 반찬 / 수·조·어·육류 · 곡류, 서류 제품 · 두류, 견과 및 종실류 · 채소, 해조류 — 원재료성 소수 행)은 어떤 끼니에도 넣지 않는다. 코드 상수는 `services/recommendation_service.py:MEAL_FOOD_GROUPS`
   - 알러지 `exclude_keywords` 이름 매칭 행 사전 제거
   - 남은 칼로리 이하(1인분 kcal 기준, 목표 미설정이면 미적용)
   - 질병 태그 수치 정렬: `low_sodium`→나트륨↑ 제외 아님 오름차순 우선, `low_sugar`/`low_gi`→당류 오름차순, `low_potassium`→칼륨, `low_phosphorus`→인. **의학 임계값을 정하지 않는다** — 처방이 아니라 상대 우선순위다 (MVP 고지 유지)
   - 정렬 상위에서 후보 30~50개를 LLM에 전달
2. **선택·설명 (LLM)** — 후보 목록(이름·kcal)을 주고 3개를 골라 끼니 구성으로 묶고 `reason`을 쓰게 한다. **items의 kcal은 LLM 출력이 아니라 DB 실측값으로 서버가 채운다.** LLM이 목록 밖 이름을 내면 그 항목은 탈락(검증은 코드).
3. **후처리 알러지 필터는 유지** (11장) — 후보 풀 사전 제거와 이중 방어.
4. **LLM 실패 시 폴백 (신규)** — 502로 끝내지 않고 후보 풀 상위 3개를 고정 `reason`(태그 기반 문구)으로 반환하며 `source='rule'`로 저장한다. 정적 데이터가 생겼으므로 추천은 HF 장애와 무관하게 항상 동작한다.

응답 계약(11장)은 변하지 않는다. `rec_date`·`meal_type` 캐시 재현성 규칙도 동일.

> **개정 (13장):** LLM 선택 단계가 제거되고 규칙 폴백이 본선으로 승격되었다. 후보 풀 추출·대분류 매핑은 13장에서도 이 장 기준 그대로다.

---

## 13. LLM 전면 배제 — 순수 데이터셋 파이프라인 (v3 — 확정)

> 2026-07-10 확정 (사용자 결정). **AI는 이미지→음식명 추출까지만 쓴다.** 음식명 이후의 모든 단계(칼로리 측정·식단 추천)는 식약처 DB만 사용한다. 12장의 "LLM 선택" 단계를 제거하고 규칙 폴백을 본선으로 승격한다.

### 결정 근거

- 일관성: 같은 입력 → 항상 같은 출력. 캐시 없이도 결정적이다.
- 비용·가용성: HF/외부 API 의존이 인식 단계 하나로 줄어든다. 추천·측정은 장애·토큰과 무관하게 항상 동작한다.
- 12장에서 구현·검증된 규칙 폴백(source='rule')이 그대로 본선이 된다.

### 파이프라인 (확정)

```
사진 → [AI] 음식명 추출 (현행 YOLO, 추후 비전 LLM 교체 검토)
     → [DB] 음식명 유사도 검색 (pg_trgm) → 영양값·kcal
     → [DB] 식단 추천 (규칙 기반 후보·선정)
```

### 유사도 검색 — `/api/nutrition/estimate` 개정 (리비전 0008)

인식 라벨과 DB 식품명은 정확히 일치하지 않는다("계란찜" vs "달걀찜", "김치찌개" vs "돼지고기 김치찌개"). 조회를 3단계로:

1. 정확 일치 (기존)
2. 정규화 일치 (공백 제거 등)
3. **pg_trgm 유사도**: `CREATE EXTENSION pg_trgm` + `GIN(food_label gin_trgm_ops)` 인덱스(0008), `similarity() >= 임계값(초기 0.3, 실측으로 조정)` 최고 1건. 응답의 `food_label`은 **매칭된 DB 행의 이름**이다(요청 라벨과 다를 수 있음 — 앱이 매칭 결과를 보여준다)

**동의어 변형 (2026-07-11 추가, `services/food_synonyms.py`):** trigram은 동의어를 잡지 못한다("계란찜"→"계란빵" 오매칭 실측). 각 단계는 라벨 하나가 아니라 `expand_variants()`가 만든 **변형 후보 전체**를 조회한다 — 표기 치환 규칙(계란↔달걀, 쇠고기→소고기, 소세지↔소시지, 낚지→낙지 등)과 검증된 라벨 별칭(스시→초밥, 밥→쌀밥, 후렌치후라이→감자튀김 등). DB에 양쪽 표기가 공존하므로(계란 9행·달걀 34행) **파괴적 치환이 아니라 후보 확장**이다. 선택 규칙: 1·2단계는 앞선 변형(원 라벨 우선)이, 3단계는 최고 유사도가 이기고 동률이면 앞선 변형 — 결정성 유지. 규칙 추가 기준: **대상 표기가 DB에 실재하는지 확인한 것만** 넣는다. 원물(무·과일)이나 일반명(생선구이)을 다른 음식으로 잇는 별칭은 금지 — 오매칭보다 404(수동 입력)가 정직하다.

> **실측 (YOLO 721라벨 전수, 2026-07-11):** 매칭 505→521(70.0%→72.3%), 계란 계열 오매칭 교정(계란찜→달걀찜, 계란국→달걀국, 쇠고기구이→소고기찜). 남은 미매칭 200개의 다수는 동의어 문제가 아니라 **식약처 음식(요리) DB의 범위 밖** — 원물 과일·채소(귤·포도·파프리카), 음료·주류(주스·맥주·와인), 가공 간식(사탕·크래커·시리얼), 외국 요리(가츠동·똠양꿍·파에야). 보강은 가공식품 DB 선별 임포트나 농축산물 DB 도입이 필요하다(후속 과제).

**LLM 호출을 제거한다.** 3단계 모두 실패하면 **404** `{"detail": "<한국어>"}` — 앱의 기존 kcal 수동 입력 경로로 유도한다. 502는 이 라우트에서 사라진다. 응답 스키마는 불변(`source`가 `mfds`/`curated`).

### 식단 추천 개정 — 순수 규칙

12장 후보 풀 추출(대분류 매핑·알러지 사전 제거·남은 칼로리·태그 정렬)은 그대로. 선정만 바뀐다:

- **선정**: 후보 풀에서 3개. `(user_id, rec_date, meal_type)` 시드의 **결정적 셔플**로 뽑는다 — 같은 요청은 캐시 없이도 같은 결과(재현성), 날이 바뀌면 다른 조합(다양성). 질병 태그가 있으면 정렬 상위 절반에서만 뽑아 수치 우선순위를 유지한다.
- **구성 다양성**: 3개의 `food_group`이 겹치지 않게 한다(가능한 경우) — "차 3잔" 같은 구성을 막는다. breakfast/lunch/dinner는 가능하면 밥류·죽류 계열 1개를 포함한다.
- **reason**: 태그 기반 한국어 템플릿(당뇨→"당류가 낮은 순으로 고른 메뉴입니다" 등, 무태그→남은 칼로리 기준 문구). LLM 문장 생성 없음.
- `source`는 항상 `'rule'`. LLM 경로·502 제거. 응답 계약(11장)·캐시 규칙 불변.

> **구현 노트 (2026-07-10 실측 반영):** 전역 단일 정렬 풀은 이 데이터에서 구성 다양성과 양립하지 않는다 — 무가당 음료가 396종이라 당류 정렬 시 snack 풀 40개를 음료가 독식한다(실측). 따라서 후보 풀은 **대분류별 상위 쿼터**(`ceil(40 ÷ 그룹 수)`, snack 10개/식사 3개)로 뽑고, "정렬 상위 절반" 제약도 **그룹 안에서** 적용한다. 태그 수치 우선순위는 그룹 내 순위로 유지된다. 구현: `services/recommendation_service.py:_candidate_pool`.

### 남는 LLM 접점

`/api/gpt-predict`(레거시 서술)만 남는다 — 앱 신규 흐름은 소비하지 않으며 정리 후보다. `gpt_oss_service`의 import 시점 `HF_TOKEN` 요구는 알려진 문제로 유지(별도 정리).

---

## 14. 가공식품 DB 보강 — estimate 조회 전용 (2026-07-11)

> 미매칭 200개(13장 실측)의 다수는 음식(요리) DB 범위 밖이었다 — 음료·주류·과자·조미료. 식약처 가공식품 DB(29.8만 행)에서 이 영역을 보강한다. 스크립트: `scripts/import_mfds_processed.py`.

### 집계 원칙

- **상품이 아니라 대표식품명 단위 일반 항목**(270종 → 선별 후 219종)으로 적재한다. 브랜드 상품명("○○사이다 245ml")은 인식 라벨과 이어질 수 없다. 영양값은 **상품별 100g/100ml 기준값의 중앙값**, 1회 제공량은 `1회 섭취참고량`의 중앙값(없으면 "100g당").
- "비스킷/쿠키/크래커" 같은 복합 대표식품명은 이름별 행으로 **분리**한다 (총 249행).
- `source='mfds_processed'`. 같은 이름의 기존 `mfds`(요리 실측)·`curated` 행은 **건드리지 않는다** — upsert 가드로 스킵 (실측 29건).
- **제외**: 대분류 식용유지류(원물 라벨이 기름으로 오폭 — 포도→포도씨유 800kcal)·특수영양식품·특수의료용도식품, "기타*" 대표식품명(잡동사니 집계), 코코아·코코아매스(분말 원료가 음료 라벨을 가로챔 — 실측 회귀로 확인).
- **추천에는 들어가지 않는다**: 추천 후보 풀은 음식 DB 대분류 화이트리스트(12·13장)라 가공식품 대분류는 자동 배제. 이 행들은 estimate 조회 전용이다.

### 조회 2b단계 추가 (nutrition_service)

식약처 라벨은 "카테고리_이름" 패턴이다("과ㆍ채주스_토마토 주스"). 접두어가 trgm 유사도를 깎아 짧은 라벨이 오폭하므로("토마토주스"→토마토케첩), **'_' 뒤 이름과의 정확(공백 무시) 일치**를 유사도 앞 단계로 넣었다. 조회는 4단계: 정확 → 공백 제거 → 접미부 정확 → pg_trgm.

### 원재료성식품 DB 보강 (같은 날 추가, `scripts/import_mfds_raw.py`)

농진청(국가표준식품성분표 1,858행)·해수부(수산물 1,846행) 원재료성 CSV로 원물 영역을 닫는다. `source='mfds_raw'`, 1,384행:

- 행이 분석 변형 단위("포도_거봉_생것")라 **일반명 중앙값 집계**. 키는 **중분류명·대표식품명 양쪽**에 잡는다 — 농진청은 품종이 중분류라(거봉·캠벨얼리) 한쪽만 쓰면 "포도" 키에 말린것(건포도 297kcal)만 남는 오염이 실측됐다. 꼬리 '류'("가리비류")와 괄호("파프리카(착색단고추)")는 뗀다 — 안 떼면 조미료 분말 520kcal이 "파프리카"를 차지한다.
- 상태 선택: **'생것' 우선**(없으면 전체 — 곶감처럼 말린 것이 본체인 키). **차류만 '추출/용액' 한정** — 말린 잎(~380kcal/100g)을 찻잔 kcal로 주면 안 된다. 유지류 제외(포도→포도씨유 오폭)는 가공식품과 동일.
- 이 CSV엔 식품중량이 없어 전부 "100g당". 우선순위는 요리(mfds)·감수(curated)·가공식품(mfds_processed) 다음 — upsert 가드로 기존 행 보존(김=조미김, 달걀=알가공 유지).

### 실측 (YOLO 721라벨 전수, 2026-07-11)

매칭 505(70.0%)→동의어 521(72.3%)→가공식품 546(75.7%)→원재료 **608(84.3%)**. 질 교정이 더 크다: 원물 라벨 93건이 요리·디저트 오매칭에서 원물 실측값으로 이동(사과: 와플 378→52, 파인애플: 피자 2,063→53, 수박: 수박화채 84→34). 남은 미매칭 113개는 대부분 **외국 요리**(가츠동·똠양꿍·파에야)와 일반명(생선구이·회) — 국내 DB 범위 밖이라 curated 시드 또는 비전 LLM 전환 시 라벨 유도가 후속 수단이다. 알려진 오폭 잔재: 칠리크랩→칠리(건고추 363kcal) 등 소수는 라벨 별칭으로 개별 관리한다.
