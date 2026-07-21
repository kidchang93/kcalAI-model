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
| `photo_s3_key` | `String(255)` | **nullable. 첫 릴리즈는 항상 NULL** (제약 5번 때문에 선반영). S3 연동 코드는 2026-07-12에 제거됐지만(자원 중단 확정) 컬럼은 향후 스토리지 재도입 대비로 유지 |
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
| `confidence` | `Numeric(5,4)` | nullable. `source='ai'`일 때 YOLO score. (4,3)이던 것을 리비전 0009에서 확장 — 0.9995 이상이 1.0으로 반올림되던 문제 |
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
| `serving_size_g` | `Numeric(6,1)` | nullable. 1인분이 몇 g인가(ml은 밀도≈1로 g 취급). 앱이 `사용자입력g ÷ serving_size_g`로 kcal 재환산. 원물 등 1회 제공량 미상은 NULL → 앱이 인분 모드로 폴백 (리비전 0019) |
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
| `GET` `PUT` | `/api/me/profile` | 신체 정보 조회·수정 (+ **BMI·권장 활동량 파생 계산**, 아래) | `user_profiles` |
| `GET` `PUT` | `/api/me/goal` | 목표 조회·수정 (Mifflin-St Jeor 자동 산출) | `user_goals` |
| `GET` | `/api/me/summary?date=` | 홈 진행률 — 섭취/목표/끼니별 합계 | `meal_logs` 집계 |
| `POST` | `/api/nutrition/estimate` | 음식 라벨 → 구조화 kcal. **캐시 우선** | `food_nutrition` |
| `POST` `GET` | `/api/meals` | 끼니 저장 · 날짜별 조회 | `meal_logs` + `meal_items` |
| `PUT` | `/api/meals/{id}` | **전체 교체 수정** (2026-07-11 추가, 아래 참고) | **소유자 검증 필수** |
| `DELETE` | `/api/meals/{id}` | soft delete (`deleted_at`) | **소유자 검증 필수** |
| `POST` `GET` | `/api/weights` | 체중 기록·추이 | `weight_logs` |

### `PUT /api/meals/{id}` — 전체 교체 (2026-07-11 확정)

부분 수정(PATCH)이 아니라 **전체 교체**다 — 기존 `PUT /api/pets/{id}`(9장)와 같은 방식으로 통일한다. 요청 본문은 `POST /api/meals`와 동일 구조(`MealUpdateRequest`는 `MealCreateRequest` 상속), 응답은 `MealResponse`.

- `meal_items`는 기존 행을 지우고 다시 넣는다. `total_kcal`은 서버가 항목 합계로 **재계산**한다 (생성 로직 재사용 — 합계의 단일 진실은 `meal_items`).
- **예외 1개**: `logged_at`을 생략(null)하면 기존 기록 시각을 **유지**한다. DB not-null 컬럼이라 null 교체가 불가능하고, 앱의 주 사용처가 "항목·끼니 종류만 고치기"이기 때문이다. `photo_s3_key`는 nullable이므로 생략 시 null로 교체된다 (전체 교체 원칙).
- 남의 끼니·soft delete된 끼니·없는 끼니는 전부 **404** — `DELETE /api/meals/{id}`와 같은 존재 은닉 규칙.

### `/api/me/profile` — BMI·권장 활동량 (2026-07-21 추가, `docs/ACTIVITY_GUIDANCE.md`)

`GET`·`PUT` 두 응답 모두에 아래 필드가 **추가**됐다(전부 nullable·기본값 있음 → 하위호환, 앱과 같은 작업 단위 배포).

```jsonc
{
  // ... 기존 프로필 필드 ...
  "bmi": 22.9,                       // 체중 ÷ 신장(m)², 소수 1자리. 키·체중이 없거나 0 이하면 null
  "bmi_category": "normal",          // underweight|normal|pre_obese|obese_1|obese_2|obese_3
  "bmi_category_label": "정상",
  "bmi_notice": "BMI는 대한비만학회 …",  // 근육량 미반영 한계 고지. 앱은 이 문구를 그대로 쓴다
  "activity_guide": {                 // 나이를 모르면 null
    "moderate_min_minutes": 150, "moderate_max_minutes": 300,
    "vigorous_min_minutes": 75, "vigorous_max_minutes": 150,   // 65세 이상은 100
    "strength_days": 2,
    "balance_days": null,             // 65세 이상만 3, 성인은 null
    "is_senior": false,
    "tips": ["..."], "source": "보건복지부 「한국인을 위한 신체활동 지침서」(2023)",
    "notice": "… 의료기기가 아니며 질병을 진단·치료·예방하지 않습니다. …"
  }
}
```

- **저장하지 않는다.** `health_service.build_profile_response`가 응답 시 계산한다 — 키·체중이 바뀌면 즉시
  따라와야 하고, 저장하면 두 값이 어긋난다(펫 `recommended_kcal`과 같은 패턴).
- 판정 기준은 `services/fitness_rules.py` 한 곳에만 둔다. **BMI는 한국(대한비만학회) 기준**이라 WHO 기준
  (25 과체중·30 비만)과 다르다 — 23·25가 경계다.
- **질병을 읽지 않는다.** 이 라우트는 `sensitive_health` 동의 없이 접근하므로, 고지 문구를 질병 유무로
  분기하려고 질병을 조회하면 동의 요건이 바뀐다(estimate에 등급을 싣지 않은 것과 같은 판단, 19장 개정 노트).
  그래서 모든 사용자에게 같은 문구(의료진 상담 안내 포함)를 준다.
- ⚠️ 앱이 **BMI를 재계산하지 않는다.** 목표 칼로리 산식은 이미 서버·앱 양쪽에 있어(앱 `onboarding/goal.tsx`)
  갈릴 위험을 안고 있다. BMI는 서버가 단일 진실이다.

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

#### 동의 버전은 **앱이 보낸 값**을 대조해 기록한다 (2026-07-16)

버전을 남기는 목적이 "누가 무엇에 동의했는지"의 증빙인데, 2026-07-16 이전에는 그 증빙이 성립하지 않았다. 가입 요청(`KakaoSignupRequest`)에 버전 필드가 **없어서**, 앱이 화면에 무엇을 그렸든 서버가 자기 상수(`TERMS_VERSION`)를 박았기 때문이다. 문서를 2.0으로 개정하고 구버전 앱이 남아 있으면 **사용자는 1.0 문구를 보고 동의했는데 DB에는 "2.0에 동의함"으로 기록**된다 — 증빙이 거짓이 되는 것이다. 민감정보 동의는 반대로 앱이 버전을 보내는데 서버가 검증하지 않아 임의 문자열이 그대로 저장됐다(실측: `"존재하지-않는-버전-9.9"` → 201).

이제 앱이 **화면에 실제로 그린 문서**의 버전을 보내고(`k-calAI-RN`의 `constants/legal.ts`·`constants/consent.ts`가 정본), 서버가 `ensure_current_version`으로 대조해 다르면 **400**("약관이 변경되었습니다. 앱을 최신 버전으로 업데이트한 뒤 다시 시도해주세요")으로 막는다. 기록되는 값은 앱이 보낸 그 버전이다.

- **대조는 연동 코드 소비 전**이다. 옛 문서를 띄운 앱의 요청이 1회용 코드만 태우고 400이 되면 사용자는 카카오 로그인부터 다시 해야 한다 (미동의 거절과 같은 규칙).
- `terms_version`·`privacy_version`은 **선택 필드**다 — 하위호환뿐이며, 보내지 않는 구버전 앱은 서버 상수로 폴백한다. 그건 "앱이 무엇을 보여줬는지 모른 채 기록하는 것"이라 증빙으로 약하므로, 두 필드가 앱에 자리잡으면 **필수로 좁힌다**.
- 모르는 `kind`는 통과시킨다 — 동의 종류가 늘 때 서버만 먼저 배포돼도 깨지지 않아야 한다.
- **문서를 개정하면 서버 상수와 앱 문서를 같은 작업 단위에서 올린다.** 서버만 올리면 기존 앱 사용자의 가입·동의가 전부 400이 된다.
- 버전 포맷이 `kind`마다 다르다(`terms`·`privacy`는 `1.0`, `sensitive_health`는 `v1.0`). 기존 데이터가 그렇게 쌓여 있어 통일하려면 마이그레이션이 필요하다 — 검증은 `kind`별 비교라 지장이 없고, `tests/test_consent_version.py`가 이 사실을 고정한다.

**저장 시 암호화 (2026-07-12, 리비전 0013):** `user_health_profiles.blood_type`·`rh`는 앱 레이어 AES-256-GCM으로 암호화해 저장한다(`crypto.py`의 `EncryptedString` 타입, ORM이 write 시 암호화·read 시 복호화). DB·쿼리 로그에는 암호문(base64)만 남는다. 키는 `HEALTH_ENCRYPTION_KEY`(base64 32B), 운영 기본키 사용 시 기동 실패. **범위는 혈액형·Rh 두 컬럼뿐이다.** `condition`·`allergen`은 참조 테이블(`condition_types`/`allergen_types`) FK·DB JOIN(`meta_service`)·추천/경고 필터에 쓰이는 **기능 키**라 암호화하지 않고 평문 코드로 유지한다 — 암호화하면 JOIN·유니크·필터가 깨진다. (이 코드들은 표준 범주 코드라 자유 PII보다 민감도가 낮기도 하다.)

**프로덕션 전 체크리스트** (MVP에서는 막지 않는다):
- ~~`/api/predict`와 `/api/s3/*`가 무인증 공개다.~~ **해결됨 (2026-07-12)**: `/api/s3/*`는 라우트 제거(S3 미사용 확정), `/api/predict`·`/api/gpt-predict`에 Bearer 인증.
- ~~`user_health_profiles`의 컬럼 암호화 여부를 결정해야 한다.~~ **해결됨 (2026-07-12, 리비전 0013)**: `blood_type`·`rh` 앱 레이어 AES-256-GCM.
- 동의 철회 시 민감정보 즉시 파기 경로가 필요하다.

### 반려동물 — 보호자 1 : N

**반려동물은 `groups.kind`가 아니라 독립 엔티티다.** 보호자(`users.id`) 한 명이 여러 마리를 가진다. 반려동물 자체는 로그인하지 않으며 메인 사용자 층이 아니다.

- 그룹에 참여시킬 때는 `group_pets`로 붙인다. 사람 멤버(`group_members`)와 테이블을 분리한다 — 다형성 FK를 피하기 위해서다.
- 급여 기록은 `meal_logs`가 아니라 `pet_feeding_logs`에 남긴다. `meal_logs.user_id`는 사람 FK다.
- **Mifflin-St Jeor는 적용되지 않는다.** 개는 RER = `70 × 체중(kg)^0.75`, MER = RER × 활동계수(중성화·연령·비만도에 따라 1.2~1.8)로 계산이 갈린다. MVP에서는 `pet_feeding_logs.kcal`을 nullable로 두고 **급여량(g)만 기록**한다. ~~칼로리 산출은 다음 단계다.~~ → 권장 칼로리(RER/MER) 산출은 18장에서 구현했다 (2026-07-11).

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

### 인증 견고화 (2026-07-12 — 리비전 0011·0012, 앱 계약 무변)

구현은 전부 `services/auth_service.py`. 상수도 그 모듈 상단에 있다.

| 항목 | 내용 | 상수 |
|---|---|---|
| OTP 브루트포스 방어 | `phone_verification_codes.attempt_count`(0011). 검증 실패마다 증가, **5회 초과 시 코드 무효화**(consumed_at). 실패 응답은 기존 400·같은 메시지 유지 | `MAX_CODE_ATTEMPTS = 5` |
| 단일 유효 코드 | 새 코드 발급 시 같은 phone+purpose의 미소비 코드를 전부 무효화한다 | — |
| request-code rate limit | 번호당 재요청 쿨다운 60초 + 시간당 5회 (DB 발급 이력 카운트, 별도 인프라 없음). 초과 시 **429** `{"detail": "<한국어>"}` — 앱은 `readErrorMessage`로 detail을 그대로 표시하므로 안전 | `REQUEST_CODE_COOLDOWN_SECONDS = 60`, `REQUEST_CODE_HOURLY_LIMIT = 5` |
| 세션 토큰 해시 저장 | `auth_sessions.token`에 sha256 해시 저장, 조회는 해시 비교. 원문은 발급 응답에서만 나간다(앱이 받는 토큰 형식 불변). 0012가 기존 평문 토큰을 해시로 변환해 **기존 세션을 보존**했다. downgrade는 불가(해시 비가역) | — |
| 휴대폰 패턴 검증 | 정규화(82→0) 후 `01[016789]` + 7~8자리만 허용. 유선번호(02...)는 400 | `_MOBILE_PHONE_PATTERN` |
| 환경 게이트 | `APP_ENV=production`이면 기동 시 `ensure_production_auth_config()` fail-fast (pepper 기본값·dev_code 노출 차단). CORS localhost 정규식은 development 전용 | `main.py` |

SMS 발송 연동·refresh 토큰은 이 범위에 없다 (사용자 결정 대기).

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
| `POST` | `/api/pets/{id}/feedings` | 급여 기록 → **201**. `amount_g`(g)만 필수, `kcal`은 nullable 수동 입력 (권장 칼로리 산출은 18장 — 급여 kcal 을 자동 계산하지 않는다) | **소유자 또는 펫이 참여한 그룹의 멤버** (가족이 함께 급여를 기록한다) |
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
  "recommended_kcal": 329,  // 권장 일일 칼로리(MER). 응답 시 계산, 미저장. 체중 없음·other 는 null (18장)
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

> **개정 (신장병 강화, `docs/CKD_NUTRITION.md`):** 위 예시에 아래 필드가 **추가**됐다 (전부 nullable·기본값 있음 → 하위호환이지만 앱과 같은 작업 단위에서 배포한다).
>
> - `items[].sodium_mg`·`potassium_mg`·`phosphorus_mg`·`protein_g` — 1인분 실측값, 미측정은 `null` (2026-07-20, CKD_NUTRITION 3-1).
> - `items[].potassium_tier`·`phosphorus_tier` — `"low"|"mid"|"high"|null`. **칼륨·인 제한 태그를 가진 사용자에게만** 채운다 (2026-07-21, CKD_NUTRITION 3-4).
> - `tips: string[]` — 질병 기반 식이 안내. 비해당은 `[]`.
> - `tier_notice: string|null` — 등급을 노출할 때만 채우는 고지.
>
> `tips`·`tier_notice`·두 `*_tier`는 **저장하지 않고 매 요청 계산**한다. 질병을 추가·삭제하면 캐시된 값이 거짓이 되기 때문이다. 그래서 `recommendation_service.get_recommendation`은 저장 행이 아니라 `RecommendationResult(recommendation, cached, tips, items, tier_notice)`를 반환하고, 라우터는 **`result.items`**(등급을 얹은 응답용)를 내보낸다 — `recommendation.items`(저장 원본)가 아니다.

---

## 12. 식약처 음식 DB 도입 — 추천 grounding (v2 5차 — 확정)

> 2026-07-10 확정. 원본: `kcal/data/식품의약품안전처_통합식품영양성분정보(음식)_20260429.csv` (19,495행 · 고유 식품명 15,568 · UTF-8 BOM). 가공식품 DB(29.8만 건 xlsx)는 보류. 원본 파일은 레포에 커밋하지 않는다.

### 원본의 두 가지 함정 (임포트가 반드시 처리)

1. **영양값은 100g/100ml 기준**(`영양성분함량기준량`)이고 1인분이 아니다. 1인분 값 = 원본값 × `식품중량` ÷ 기준량. 식품중량 누락 12행은 100g 기준으로 저장하고 `serving_desc`를 `"100g당"`으로 남긴다. 같은 `식품중량`의 숫자를 `serving_size_g`(1인분이 몇 g)로도 저장한다 — g/ml 구분 없이 밀도≈1로 그대로. 식품중량 누락 행은 `serving_desc="100g당"`이므로 `serving_size_g=100`(100g 기준값 → 사용자 g 입력 시 kcal × 입력g/100, 2026-07-18).
2. **식품명이 유일하지 않다** (프랜차이즈 동일 메뉴가 업체별 중복, 최대 20행). 같은 이름은 식품중량이 있는 행 우선으로 1행만 선택한다.

### `food_nutrition` 확장 (리비전 0007)

추가 컬럼 (전부 nullable): `sugar_g` · `sodium_mg` · `potassium_mg` · `phosphorus_mg` (Numeric) · `food_group` (String(30), 원본 `식품대분류명`). `source`에 `'mfds'` 값 추가. 임포트는 idempotent upsert이며, **같은 라벨의 `source='llm'` 행은 mfds가 덮어쓴다** — 실측이 추정에 우선한다.

**`serving_size_g` 확장 (리비전 0019):** 앱이 사용자가 먹은 g을 자유 입력하면 kcal을 재계산할 수 있도록, 1인분이 몇 g인지(= `serving_desc`가 가리키는 1회 제공량의 무게)를 담는 `Numeric(6,1)` nullable 컬럼. 앱은 `serving_ratio = 사용자입력g ÷ serving_size_g`로 환산하고, **ml은 밀도≈1로 g과 동일 수치 취급**(국·죽·면 국물류 — "291.90ml"이면 291.9). 값이 없으면(원물 등 1회 제공량 미상) NULL → 앱이 인분 모드로 폴백. 채우는 경로: `import_mfds_food.py`는 원본 `식품중량` 숫자를(누락 "100g당" 행은 100), `correct_common_foods.py`·`seed_curated_foods.py`는 `serving_desc`에서 g/ml 숫자를 파싱(공용 헬퍼 `services/serving_size.py`, "100g당"·"1그릇"처럼 무게 없는 표기는 None), estimate의 llm 신규 적재는 Gemini `serving_desc`를 같은 헬퍼로 파싱(19장). `import_mfds_raw.py`·`import_mfds_processed.py`도 채운다(2026-07-18) — "100g당"/"100ml당" 기준량형은 `serving_size_g=100`(100g 기준값 → 사용자 g 입력 시 kcal × 입력g/100), 가공식품 "1회 제공량 (약 Xg)"은 공용 헬퍼로 파싱. upsert `set_`에 `serving_size_g`를 넣되 `where source in (...)` 가드가 있어 재임포트가 다른 경로(mfds 요리·curated 보정)의 값을 덮지 않는다. **estimate 응답에 `serving_size_g: float | None`으로 실린다(앱 계약 변경 — `k-calAI-RN`과 함께 배포).**

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
사진 → [AI] 음식명 추출 (Gemini 비전 단일 백엔드 — YOLO/torch 제거, 2026-07-12)
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

> **개정 (19장, 2026-07-13):** 조회 실패 시의 **404가 최종이 아니게 됐다** — 미등록 라벨은 LLM으로 **1회만** 추정해 `source='llm'`으로 적재하고, 이후 같은 라벨은 그 행을 읽는다. **조회 경로에 LLM은 여전히 없다**(읽기는 항상 DB). 이 장의 결정성 원칙("같은 입력 → 항상 같은 출력")은 "LLM을 안 쓴다"가 아니라 **"추정값을 동결한다"**로 충족된다. 추정 실패·게이트 탈락 시에는 이 장 그대로 404다.

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
- 이 CSV엔 식품중량이 없어 전부 "100g당". 우선순위는 요리(mfds)·감수(curated)·가공식품(mfds_processed) 다음 — upsert 가드로 기존 행 보존(김=조미김, 달걀=알가공 유지). `serving_size_g`(리비전 0019)는 원물·가공식품 임포트(`import_mfds_raw.py`·`import_mfds_processed.py`)에서 **"100g당" 기준량형은 `serving_size_g=100`으로 채운다**(2026-07-18) — 100g/100ml 기준값이라 사용자가 g을 입력하면 kcal × 입력g/100으로 정확히 환산된다. 가공식품 "1회 제공량 (약 Xg)"은 공용 헬퍼(`services/serving_size.py`)로 파싱한다. upsert `set_`에 `serving_size_g`를 넣되 `where source in (...)` 가드로 다른 경로(mfds 요리·curated 보정)가 채운 값은 덮지 않는다. 무게 없는 표기("반 모" 등)만 NULL로 남고 앱은 인분 모드로 폴백한다.

### 실측 (YOLO 721라벨 전수, 2026-07-11)

매칭 505(70.0%)→동의어 521(72.3%)→가공식품 546(75.7%)→원재료 **608(84.3%)**. 질 교정이 더 크다: 원물 라벨 93건이 요리·디저트 오매칭에서 원물 실측값으로 이동(사과: 와플 378→52, 파인애플: 피자 2,063→53, 수박: 수박화채 84→34). 알려진 오폭 잔재: 칠리크랩→칠리(건고추 363kcal) 등 소수는 라벨 별칭으로 개별 관리한다.

**curated 시드로 외국 요리·일반명 보강 (2026-07-12):** 남은 미매칭 113개(외국 요리 가츠동·똠양꿍·파에야, 일반명 생선구이·회 등 — 국내 식약처 DB 범위 밖)를 `scripts/seed_curated_foods.py`로 대표 65항목 채웠다(1인분 kcal 근사값, `source='curated'`, macros·food_group은 우선 NULL). **721 실측: 84.3%→674(93.5%)**, 미매칭 113→47. curated는 추천 후보 풀(`source='mfds'`)에 안 들어가므로 estimate 전용이다. 완벽 커버리지가 아니라 "동작하는 뼈대 + 대표 항목" 방침 — 테스트하며 `CURATED_FOODS`에 계속 추가한다. 남은 47개는 주로 원물·주류·소스류.

**1인분 값 보정 (2026-07-16):** 식약처 원본의 **식품중량(1인분 무게)이 일부 음식에서 비현실적으로 작아**(떡볶이 75g·제육볶음 136g·달걀말이 49g) 1인분 kcal이 크게 과소평가됐다. 원물(mfds_raw)은 "100g당"이라 사과 한 개(약 180g)를 100g로 계산했다. → 사용자 체감 "칼로리가 너무 작게 나온다". `scripts/correct_common_foods.py`로 자주 먹는 **31개 음식의 1인분 값만 현실화**(제육볶음 202→430·떡볶이 193→360·돈가스 148→560·볶음밥 193→600·사과 52→95·고구마 134→180 등). 계산 **모델(1인분 × serving_ratio 0.5~2)은 불변** — 앱은 그대로다. `seed_curated_foods.py`와 달리 **source 제한 없이 덮어쓰고**(대상이 이미 mfds/raw로 존재), 보정 후 `source='curated'`라 mfds 재적재(WHERE source in llm,mfds)에도 보정이 유지되지만 추천 후보 풀(`source='mfds'`)에선 빠진다(estimate 전용). 매크로·food_group은 옛 서빙 기준이라 비운다. 이미 정상인 음식(김치찌개 244·비빔밥 634·쌀밥 300·짜장면 683)은 미보정.

---

## 15. 주/월 추이 집계 API (2026-07-11 확정)

> 앱 추이 탭(주/월 섭취 그래프·목표 달성률)의 선행 작업. 기존 `GET /api/me/summary`는 하루 단위라 추이를 그리려면 날짜별 N회 호출이 필요했다. 신규 테이블 없음 — `meal_logs` 집계 전용이다.

| 메서드 | 경로 | 역할 | 선행 조건 |
|---|---|---|---|
| `GET` | `/api/me/trends?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` | 기간 내 날짜별 섭취 kcal·끼니 수 집계 | `Authorization: Bearer` 필수 |

### 검증 규약

- `end_date >= start_date`. 위반 시 **400** + 한국어 `detail`.
- 범위는 **최대 92일**(양끝 포함 — 3개월 그래프 상한). 초과 시 **400**.
- 날짜 형식 오류는 FastAPI 기본 **422**.

### 응답 스키마 (확정)

```jsonc
{
  "start_date": "2026-07-05",
  "end_date": "2026-07-11",
  "target_kcal": 2017,          // 현재 열린 목표. 미설정 시 null. 0 이 아니다 — summary(4장)와 동일 규칙
  "days": [                     // 범위 내 모든 날짜를 오름차순으로 채운다. 기록 없는 날도 0 으로 존재한다 (그래프용)
    { "date": "2026-07-05", "consumed_kcal": 0, "meal_count": 0 },
    { "date": "2026-07-11", "consumed_kcal": 288, "meal_count": 1 }
  ]
}
```

### 집계 규칙

- `meal_logs` 기준, soft delete(`deleted_at IS NOT NULL`) 제외 — 4장 summary 와 동일.
- 날짜 경계는 summary 와 같은 **UTC 자정** 기준(`logged_at`을 UTC 날짜로 절단).
- **날짜별 GROUP BY 단일 쿼리**로 집계한다. 날짜 수만큼 쿼리를 반복하지 않는다.
- `target_kcal`은 조회 시점의 열린 목표 하나다. 과거 목표 이력별 달성률이 필요해지면 그때 별도 계약으로 확장한다.
- **체중은 이 API에 넣지 않는다.** 앱은 기존 `GET /api/weights`를 그대로 쓴다.

---

## 16. 기록 시 알러지·질병 경고 판정 API (2026-07-11 확정)

> 기획 근거: `k-calAI-RN/docs/HEALTHCARE_EXPANSION.md` 12장 — "사진 분석 결과에 제외 재료가 보이면 기록할 때 경고합니다". 앱이 사진 분석(`/api/predict`) 결과를 끼니로 기록하기 전에 호출해, 사용자의 질병·알러지에 걸리는 라벨이 있으면 경고를 그린다.

### 노출 원칙 — 판정 결과만 내려준다

`condition_types.exclude_keywords` · `allergen_types.exclude_keywords`는 추천 엔진 내부용이며 **메타 API로 노출하지 않는다**(10장). 이 API도 키워드 사전을 내려주지 않고 **서버가 판정한 결과만** 반환한다.

단, 응답의 `matched_keyword`로 **걸린 키워드 원문 1개**는 노출한다 — "왜 걸렸는지"를 앱이 설명하는 데 필요한 최소 노출이며, 전체 키워드 사전은 여전히 비노출이다. (2026-07-11 확정)

### 테이블 변경 — `condition_types.exclude_keywords` (리비전 0010)

10장의 `condition_types`에는 `dietary_tags`(정렬용 상대 우선순위)만 있어 문자열 키워드 판정이 불가능했다. 0010에서 `exclude_keywords` JSONB(문자열 배열, NOT NULL)를 추가하고 시드를 넣는다:

| condition_types.code | exclude_keywords |
|---|---|
| `diabetes` | `["설탕", "시럽", "꿀", "사탕", "초콜릿", "케이크"]` |
| `pregnancy` | `["소주", "맥주", "와인", "막걸리", "육회", "생선회"]` |
| `ckd` | `["젓갈", "장아찌", "라면"]` |
| `cancer` | `["육회", "생선회"]` |
| `hypertension` | `["젓갈", "장아찌", "라면"]` |

시드는 초기값이며 전문가 감수 전까지의 잠정 사전이다. **추천 엔진은 이 컬럼을 읽지 않는다** — 추천의 질병 반영은 기존대로 `dietary_tags` 정렬(13장), 알러지 키워드 제외만 후보 필터에 쓴다. 추천 동작 불변.

### API

| 메서드 | 경로 | 역할 |
|---|---|---|
| `POST` | `/api/nutrition/warnings` | 기록 직전 경고 판정. **Bearer + `sensitive_health` 동의 필수(403)** — 질병·알러지를 조회에 사용하므로 7장 규약을 따른다 |

요청:

```jsonc
{ "food_labels": ["계란찜", "달걀찜"] }   // 1~10개, 중복 허용 — 서버가 dedupe
```

- 빈 배열 / 10개 초과 / 문자열 아님 → **422** (스키마 검증). 라벨은 각 1~100자.

응답 (200 — 해당 없으면 빈 배열):

```jsonc
{
  "warnings": [
    {
      "source": "condition",        // "condition" | "allergy"
      "code": "diabetes",           // condition_types.code 또는 allergen_types.code
      "label": "당뇨",               // 한국어 표시명 (label_ko)
      "matched_keyword": "설탕",     // 어떤 키워드에 걸렸는지 (최소 노출 — 위 원칙)
      "matched_label": "설탕물",     // 입력 중 어떤 라벨이 걸렸는지
      "nutrient": null              // 영양 축 경고면 "sodium"|"potassium"|"phosphorus", 아니면 null
    }
  ]
}
```

> **개정 (2026-07-21, `docs/CKD_NUTRITION.md` 3-5):** 항목에 `nutrient_mg: float|None`·`tier: "low"|"mid"|"high"|None`이 **추가**됐다(하위호환). 그 축의 1인분 실측값과 상대 등급이며, 앱이 "칼륨이 높은 편이에요 (1인분 681mg · 높음)"처럼 근거를 함께 보인다.
>
> 판정 축도 늘었다 — **이름 키워드에 걸리거나 실측 등급이 `high`면** 경고한다. 이름 목록은 원물 중심이라 요리명(안동찜닭 칼륨 3,120mg)이 통째로 새고 있었다. 실측만으로 발동한 경고는 `matched_keyword`가 **빈 문자열**이다. 실측 조회는 유사도 매칭을 쓰지 않는다(틀린 경고 방지).

> **2026-07-20 강화 (신장병·고혈압, `docs/CKD_NUTRITION.md` 3-3):** 영양 제한 태그(low_sodium/low_potassium/low_phosphorus)가 있는 질병은 exclude_keywords 대신 대한신장학회 지침 분류(`services/ckd_food_rules.py`)로 판정하고, `nutrient`(어느 영양소가 높은지)를 담아 "칼륨이 높은 편"으로 안내한다. 그 외 질병·알러지는 아래 규칙 그대로(nutrient=null). `nutrient`는 **추가·nullable → 하위호환**(앱·구버전 서버 모두 안전). dedupe 단위에 `nutrient`가 추가돼, 한 음식이 칼륨·인 두 축에 걸리면 각각 보고한다.

### 판정 규칙 (영양 축이 없는 질병·알러지 — 기존)

- 사용자의 `user_conditions` · `user_allergies`에 연결된 참조 행의 `exclude_keywords`를 모아, 각 `food_label` 문자열에 키워드가 **부분 문자열로 포함**되는지 검사한다 — 추천 후처리 필터(11장)와 **같은 매칭 함수**를 쓴다 (`services/meta_service.py:match_exclude_keyword`, 추천·경고 공용).
- 행 순서는 condition 먼저, 각 소스 안에서는 `sort_order` 오름차순. 라벨은 입력 순서(중복 제거 후).
- 한 (참조 행, 라벨) 쌍에서는 **첫 매칭 키워드 1개**만 보고한다 (추천 필터와 동일).
- dedupe 단위: `(source, code, matched_label)` — 입력에 같은 라벨이 중복돼도 경고는 1건이다.
- `is_active=false`인 참조 행도 사용자에게 이미 연결돼 있으면 판정에 포함한다 (사용자 데이터가 남아 있는 한 경고가 우선).

---

## 17. 그룹 라이프사이클 API (2026-07-11 확정)

> 9장의 생성·참여만 있고 나올 방법이 없던 구멍을 닫는다. 스키마 변경 없음 — 마이그레이션 없이 기존 5테이블로 구현.

9장의 규약(Bearer 필수, `{"detail": "<한국어>"}`, `ValueError`→400 / `PermissionError`→403 / `LookupError`→404)을 그대로 따르되, **파괴적 라우트는 비멤버에게 그룹 존재 자체를 숨긴다(404)** — 남의 펫 404 은닉과 같은 규칙이다. (9장 `GET /api/groups/{id}`의 비멤버 403은 초대 코드 기반 참여 흐름을 위한 조회 실패이며 그대로 유지한다.)

| 메서드 | 경로 | 역할 | 권한·오류 |
|---|---|---|---|
| `DELETE` | `/api/groups/{id}/members/me` | 멤버 탈퇴 → `{message}`. 탈퇴자 소유 펫의 `group_pets` 연결도 함께 해제한다 (펫 공유의 전제인 소유자 멤버십이 사라지므로) | 멤버만. **소유자는 400** ("그룹 삭제로 진행" 안내). 비멤버·없는 그룹 404 |
| `DELETE` | `/api/groups/{id}` | 그룹 삭제 → `{message}`. `group_members`·`group_pets` 연결을 함께 지우고 그룹 행을 **물리 삭제**한다 (`groups`에 `deleted_at` 없음). **펫·급여 기록은 삭제하지 않는다** — 소유자·펫에 귀속 | **소유자만.** 비소유 멤버 403, 비멤버 404 (존재 은닉) |
| `DELETE` | `/api/groups/{id}/members/{user_id}` | 멤버 제거 → `{message}`. 제거 대상 소유 펫의 `group_pets` 연결도 함께 해제 (탈퇴와 동일) | **소유자만** (비소유 멤버 403, 비멤버 404). 소유자 자신 제거 400, 대상이 멤버가 아니면 404 |
| `DELETE` | `/api/groups/{id}/pets/{pet_id}` | 펫 참여 해제 → `{message}` | **펫 소유자 또는 그룹 소유자.** 그 외 멤버 403, 비멤버 404, 미참여·soft delete된 펫 404 |

### 데이터 관계 결정 (근거)

- **급여 기록(`pet_feeding_logs`)은 어떤 라우트에서도 삭제하지 않는다.** `pet_id` FK로 펫에 귀속되며, 9장에서 펫 soft delete 시에도 기록을 지우지 않고 조회만 차단하는 것과 같은 규칙이다. 그룹은 기록의 소유자가 아니라 공유 통로일 뿐이다.
- **그룹 삭제는 물리 삭제다.** `groups`·`group_members`·`group_pets`에는 `deleted_at`이 없고(리비전 0004), 연결 테이블만 지우면 다른 엔티티(사용자·펫·기록)는 무손실이므로 soft delete를 새로 도입하지 않았다. `invite_code`(unique)도 함께 반환된다.
- **탈퇴·제거 시 해당 사용자 소유 펫의 그룹 참여를 자동 해제한다.** 9장의 펫 참여 조건이 "그룹 멤버이면서 펫 소유자"이므로, 소유자가 멤버가 아니게 되면 참여의 전제가 깨진다. 남은 멤버가 그 펫의 급여 기록에 계속 접근하는 것(`_get_accessible_pet`의 그룹 공유 경로)을 막는 개인정보 최소노출 결정이기도 하다.
- 라우트 등록 순서: `/members/me`를 `/members/{user_id}`보다 먼저 등록한다 — `me`가 int 경로 매개변수에 걸려 422가 나는 것을 막는다 (`api/group_api.py`).

### 실측 (2026-07-11, 로컬)

소유자 탈퇴 400 · 비멤버 탈퇴/삭제/해제 404 · 무관 멤버 펫 해제 403 · 펫 소유자/그룹 소유자 해제 200 · 비소유 멤버 삭제/제거 403 · 소유자 자신 제거 400 · 삭제 후 상세 404, 그룹 삭제 후 `pets`·`pet_feeding_logs` 행 보존 확인.

---

## 18. 회원 탈퇴(계정 파기) · 펫 권장 칼로리 (2026-07-11 확정)

> 스키마 변경 없음 — 마이그레이션 없이 기존 테이블·컬럼으로 구현 (리비전 0010 유지). 구현: `services/account_service.py` · `api/account_api.py` · `services/pet_service.py`(RER/MER).

### `DELETE /api/me` — 회원 탈퇴

개인정보보호법 제21조(개인정보의 파기)에 따라, 탈퇴(= 처리 목적 달성·동의 철회)한 사용자의 개인정보는 지체 없이 파기해야 한다. 따라서 탈퇴는 **soft delete가 아니라 물리 삭제**다 — 7장 "민감정보는 soft delete가 아니다"와 같은 원칙을 계정 전체로 확장한 것이다. `meal_logs.deleted_at`이 찍힌 soft delete 행도 파기 대상이다.

- **Bearer 필수.** 성공 시 200 `{"message": "회원 탈퇴가 완료되었습니다. 모든 개인 데이터가 파기되었습니다."}`.
- 세션 행을 파기하므로 해당 유저의 **모든 토큰이 즉시 무효(401)** 가 된다.
- **트랜잭션 하나** — `commit`은 마지막 한 번이고, 중간 실패 시 전체 롤백된다 (api 레이어는 실패를 `error_logger`에만 남기고 500 한국어 메시지를 준다).
- 동의 이력(`user_consents`)도 함께 파기한다. 동의 증빙 보존(분쟁 대비)이 필요하다는 판단이 서면 별도 분리 보관을 도입한다 — **잠정 결정**.

#### 삭제 연쇄 (FK 실측 기반 — 전 FK가 `ON DELETE NO ACTION`이라 자식 → 부모 순서가 강제된다)

| 순서 | 테이블 | 조건 | 처리 |
|---|---|---|---|
| 1 | `auth_sessions` | `user_id` | 물리 삭제 (토큰 전체 무효) |
| 2 | `kakao_link_codes` | `kakao_id` (FK 없음 — 회원번호로 귀속) | 물리 삭제 |
| 2-2 | `user_subscriptions` · `vision_usage_daily` | `user_id` | 물리 삭제 (`plans` 참조 테이블은 불변) |
| 2-3 | `billing_keys` | `user_id` | **물리 삭제** — 카드를 다시 긁을 수 있는 자격증명이라 보존할 이유가 없다 (암호문이어도 마찬가지) |
| 2-4 | `payments` | `user_id` | **익명화 (`user_id = NULL`), 행은 보존** — 아래 참고 |
| 3 | `user_consents` | `user_id` | 물리 삭제 (잠정 — 위 참고) |
| 4 | `user_health_profiles` · `user_conditions` · `user_allergies` | `user_id` | 물리 삭제 (7장 파기 규칙과 동일) |
| 5 | `meal_items` | `meal_log_id ∈ 내 meal_logs` | 물리 삭제 (soft delete된 끼니의 항목 포함) |
| 6 | `meal_logs` · `weight_logs` · `user_goals` · `user_profiles` · `diet_recommendations` | `user_id` | 물리 삭제 |
| 7 | `pet_feeding_logs` | `pet_id ∈ 내 pets` | 물리 삭제 — 기록은 작성자가 아니라 **펫에 귀속**이다. 타인이 내 펫에 남긴 기록도 함께 파기된다 |
| 8 | `group_pets` | `pet_id ∈ 내 pets` (남의 그룹 참여분 포함) | 물리 삭제 |
| 9 | `group_pets` · `group_members` | `group_id ∈ 내 소유 groups` (타인 펫 연결·타인 멤버십) | 물리 삭제 — **소유 그룹은 그룹째 삭제** (17장 그룹 삭제와 동일 연쇄) |
| 10 | `group_members` | `user_id` (남의 그룹 멤버십) | 물리 삭제 — **그룹 자체는 보존** |
| 11 | `groups` | `owner_id` | 물리 삭제 |
| 12 | `pets` | `owner_id` (soft delete된 펫 포함) | 물리 삭제 |
| 13 | `users` | `id` | 물리 삭제 |

#### 타인 데이터에 남는 참조 — 실측 근거

- `pet_feeding_logs`에는 **작성자 FK가 없다** (컬럼: `pet_id`·`fed_at`·`food_label`·`amount_g`·`kcal`, `models/pet_model.py` 실측). 따라서 **내가 타인 펫에 남긴 급여 기록은 참조가 없어 그대로 보존**된다 — 삭제도 null화도 불필요하다. 기록은 펫의 데이터다 (17장 "그룹은 공유 통로일 뿐"과 같은 원칙).
- `users`를 참조하는 FK **17개** 전부와 `pets`·`groups`·`meal_logs`의 자식 FK가 위 표에서 전부 소거된다. DB `information_schema` 전수 조회로 대조했다. **`tests/test_account_service.py`가 이 대조를 자동화한다** — FK가 늘었는데 연쇄에 없으면 테스트가 그 테이블 이름을 지목하고 실패한다.

#### 🔴 결제 원장은 파기하지 않고 익명화한다 (2026-07-16)

**두 법이 반대 방향을 가리킨다.** 개인정보보호법 제21조는 탈퇴 시 파기하라 하고, 전자상거래법 제6조는 대금결제 기록을 5년 보존하라 한다. 둘을 동시에 지키는 방법은 **원장 행은 남기고 개인 식별자만 끊는 것**이다 — `payments.user_id = NULL`로 만들면 주문번호·금액·일시·결제수단은 감사 근거로 남으면서 그 행은 더 이상 특정 개인과 연결되지 않는다. `order_id`는 `ord_{uuid4}`라 회원 정보를 담지 않고(`_new_order_id`), `fail_reason`은 우리가 만든 한국어 문구다(23장). 조회는 `user_id` 일치로만 하므로(`payment_service`) 익명화된 행은 누구에게도 노출되지 않는다.

`billing_keys`는 **반대로 반드시 파기**한다. 거래 기록이 아니라 카드 재청구 자격증명이라 보존할 이유가 없다.

리비전 **0018**이 `payments.user_id`를 nullable로 바꿨다. FK는 그대로 `NO ACTION`으로 둔다 — `ON DELETE SET NULL`로 DB에 맡기면 "익명화한다"는 의도가 코드에서 사라지고, 실수로 `users`를 지웠을 때 원장이 조용히 끊기는 것을 막지 못한다.

> **이것이 고쳐지기 전까지 결제 이력이 있는 회원은 탈퇴가 500으로 실패했다** — `/api/billing/confirm`을 한 번이라도 부른 회원 전부이며, **청구가 실패한 사람도 포함**된다(`_create_ready_payment`가 청구 전에 `ready` 행을 커밋한다). 원인은 이 표의 낡음이다: 삭제 연쇄는 2026-07-11 작성인데 `payments`·`billing_keys`는 **0017(2026-07-16)**에 추가됐고 목록이 갱신되지 않았다. 위 FK 대조 테스트가 같은 사고를 막는다.

#### 실측 (2026-07-11, 로컬 — 일회용 계정 2개)

가입→동의 3종→프로필·목표·건강정보·질병·알러지→끼니 2건(1건 soft delete)→체중→추천 캐시→펫 4마리→소유 그룹(펫 참여·급여 기록 포함)→타인 그룹 멤버 참여 상태에서 `DELETE /api/me` → 200, 같은 토큰 401, 위 표의 관련 테이블 **전부 0행** 실측. 타인 그룹은 보존되고 내 멤버십만 제거, 내 소유 그룹은 그룹째 삭제(참여했던 타인 펫·기록은 보존), 내가 타인 펫에 남긴 급여 기록 보존 확인.

### 펫 권장 일일 칼로리 (RER/MER) — `recommended_kcal`

6장에서 "다음 단계"로 미뤄둔 항목. **스키마 변경 없이** 기존 `pets.weight_kg`·`species`로 응답 시마다 계산한다 (저장하지 않는다 — 체중 수정에 항상 따라간다).

```
RER = 70 × 체중(kg)^0.75
recommended_kcal = round(RER × MER 계수)
```

| species | MER 계수 | 근거 |
|---|---|---|
| `dog` | **1.6** | 성체·중성화 가정의 보수적 기본값 |
| `cat` | **1.2** | 〃 |
| `other` | 산출 안 함 (`null`) | 종 계수 근거 없음 |

- **계수는 잠정값이다.** 실제 MER 계수는 중성화·연령·비만도·활동량에 따라 1.2~1.8로 갈리지만(6장), MVP는 `is_neutered`·`birth_year`를 계수에 반영하지 않고 성체·중성화 가정의 보수값 하나로 고정한다. 수의학 감수 시 세분화한다.
- `weight_kg`가 `null`이면 `recommended_kcal`도 `null`.
- 노출 위치: `PetResponse` (`POST /api/pets` · `GET /api/pets` · `PUT /api/pets/{id}`). 그룹 상세의 `pets` 요약에는 넣지 않는다.
- **급여 기록의 `kcal` 수동 입력 계약은 그대로다** — `recommended_kcal`은 목표치일 뿐 `pet_feeding_logs.kcal`을 자동 계산하지 않는다.

실측: dog 4.2kg → 329 (70×4.2^0.75×1.6=328.6), cat 3.5kg → 215, PUT으로 6.0kg 변경 → 429 재계산, other 5.0kg → null, 체중 없는 dog → null.

---

## 19. 미등록 음식 LLM 추정·적재 (2026-07-13 확정)

> 13장은 "LLM 전면 배제"로 커버리지를 **404로 닫았다**. 그 결과 데이터셋 밖 음식(721 실측 기준 47개 + 실사용 롱테일)은 영구히 수동 입력이었다. 이 장은 13장의 **결정성 원칙은 유지한 채** 커버리지만 연다.

### 원칙 — LLM은 쓰기 경로에만, 읽기는 항상 DB

13장이 LLM을 배제한 이유는 "같은 입력 → 항상 같은 출력"이었다. 그 요구는 LLM을 **조회에서 빼는 것**으로 충족되지, LLM을 아예 안 쓰는 것으로만 충족되는 게 아니다.

```
estimate(라벨)
  1패스  데이터셋 4단계 조회 (mfds·curated·mfds_processed·mfds_raw)   ← 13·14장 그대로
  2패스  llm 캐시 조회 — 정확·정규화(공백 무시) 일치만
  3      둘 다 실패 → Gemini 1회 추정 → 게이트 → insert(source='llm') → 그 값을 응답
```

**미등록 라벨은 생애 딱 한 번 LLM을 탄다.** 적재된 값은 **동결**되고, 이후 같은 라벨은 그 행을 읽는다 — 사용자에게 LLM의 값 흔들림이 보이지 않는다. `meal_items`에 기록된 과거 kcal과도 어긋나지 않는다.

### 2패스에 유사도(trgm)를 쓰지 않는 이유

llm 행은 근사값이다. 여기에 trgm 유사도 매칭을 허용하면 **한 번 잘못 추정된 값이 이름이 비슷한 다른 음식들로 번진다**(추정 오차 위에 추정 매칭이 얹히는 구조). llm 행은 자기 이름 정확 일치(공백 무시 포함)일 때만 반환한다. 유사도는 실측 데이터셋(1패스)에만 허용한다.

### 적재 게이트 — 통과 못 하면 버리고 404

추정값을 무검증으로 넣으면 DB가 **영구히** 오염된다(동결되므로 자정되지 않는다). `services/gemini_nutrition_service.py`:

| 게이트 | 기준 | 탈락 시 |
|--------|------|---------|
| 음식 여부 | `is_food=false`면 폐기 | 404 (적재 안 함) |
| kcal 범위 | 1인분 1~2,000kcal | 404 (적재 안 함) |
| 매크로 정합성 | `탄4+단4+지9`가 kcal과 ±30% 이내 | **macros만 NULL로 버리고 kcal은 적재** |
| temperature | `0.0` — 그 1회의 흔들림을 줄인다 | — |

매크로 검증은 50kcal 미만에서 건너뛴다(반올림 오차가 비율을 지배한다). 게이트 탈락은 "오매칭보다 404가 정직하다"는 13장 원칙을 그대로 따른다.

### 동시성 — ON CONFLICT DO NOTHING

같은 라벨이 동시에 요청되면 둘 다 Gemini를 타지만 **행은 하나만 남고**, 진 쪽은 이긴 쪽의 행을 읽는다(값이 갈라지지 않는다). 이미 실측(mfds 등) 행이 있는 라벨도 충돌로 스킵되므로 **실측값을 절대 덮지 않는다**.

### 신뢰도 사다리 · 승격 경로

```
mfds(실측) > curated(감수) > mfds_processed > mfds_raw > llm(추정)
```

`llm`은 최하위다. import 스크립트에 "llm 행은 mfds가 덮어쓴다, curated는 보존" 가드가 이미 있어, 나중에 식약처가 그 음식을 커버하면 추정값은 **자동으로 실측값에 자리를 내준다**. 검증된 llm 행은 사람이 감수해 `scripts/seed_curated_foods.py`의 `CURATED_FOODS`로 승격시킨다(그러면 `source='curated'`가 되어 코드에 커밋되고 추천 후보 진입도 검토 가능).

`llm` 행은 `food_group`이 NULL이라 **추천 후보 풀(`source='mfds'`)에 들어가지 않는다** — estimate 전용이다.

### API 계약 변경

`POST /api/nutrition/estimate` — 스키마 불변, 상태코드 1개 추가:

| 코드 | 언제 | 앱 처리 |
|------|------|---------|
| 200 | 데이터셋·캐시 히트 또는 **신규 추정 성공** | `source='llm'`이면 **"추정값" 배지** + 수정 쉽게 |
| 404 | 추정도 실패(음식 아님·게이트 탈락) | 기존 kcal 수동 입력 |
| **503** (신규) | Gemini 장애·타임아웃·키 없음 | 재시도 또는 수동 입력 |

`cached`의 의미가 부활한다: 기존 행을 읽었으면 `true`, 이번 요청에서 새로 추정·적재했으면 `false`.

503을 404로 뭉개지 않는 이유 — "이 음식은 DB에 없다"와 "지금 서버가 추정을 못 한다"는 다른 사건이다. 후자를 404로 감추면 **장애가 미매칭 통계에 묻힌다**.

### 스키마 변경 없음

`food_nutrition`의 기존 컬럼(`source='llm'`)으로 충분하다. 마이그레이션 없다. `food_label`의 UNIQUE 제약이 "한 라벨 = 한 값"을 DB 레벨에서 보장한다.

> **개정 (serving_size_g, 2026-07-18 · 리비전 0019):** 위 "스키마 불변·마이그레이션 없다"는 19장 원래 기능에 한한다. 이후 `estimate` 응답에 **`serving_size_g: float | None`**을 추가했다(1인분이 몇 g인가 — 12장 스키마 절). 앱이 사용자가 먹은 g을 자유 입력하면 kcal을 재계산하는 환산 계수이며 **앱 계약 변경이라 `k-calAI-RN`과 같은 작업 단위로 배포**한다. llm 신규 적재는 Gemini가 준 `serving_desc`("1인분(약 350g)")를 공용 헬퍼(`services/serving_size.py`)로 파싱해 채운다 — **프롬프트·응답 스키마는 건드리지 않는다**(기존 serving_desc 파싱으로 충분). 파싱 실패 시 NULL. 나머지 컬럼·게이트·동결 규칙은 불변.

### 실측 (2026-07-13, 로컬)

김치찌개 → mfds 244kcal (LLM 호출 0회) / 뿔레아사도(미등록) → LLM 1회, 400kcal·`1인분(약 300g)`·탄5.5·단45.0·지22.0 적재(매크로 합 400kcal로 정합) / 재요청·공백 변형("뿔레 아사도") → 캐시 히트, 같은 행·같은 값, **LLM 0회** / "플라스틱 의자" → 404, **DB 미적재**.

### 인식 음식 전량 적재 (프리워밍, 2026-07-13 추가 · 2026-07-16 다중 음식으로 개정)

`/api/predict`는 사진에 있는 **서로 다른 음식**(밥·국·반찬 등)을 각각 돌려준다(최대 10, 22장). 사용자는 그중 일부를 끼니로 기록한다. 인식된 라벨은 전부 **버리기 아까운 결과**이므로, predict가 응답을 보낸 **뒤** 백그라운드(`BackgroundTasks`)로 전 라벨을 조회·적재한다 — `services/nutrition_service.prewarm_labels()`.

- 이미 데이터셋·llm 캐시에 있으면 **LLM을 타지 않는다**. 대부분의 라벨이 여기서 끝나므로 호출량은 크게 늘지 않는다.
- 실패(음식 아님·게이트 탈락·Gemini 장애)는 **삼킨다**. 백그라운드가 사용자 응답을 깨뜨리면 안 되고, 실패한 라벨은 다음에 다시 시도되면 그만이다.
- 요청 세션은 응답과 함께 닫히므로 **자체 세션**(`SessionLocal`)을 연다.
- 부수 효과: 사용자가 **어느 음식을 기록하든 estimate가 캐시 히트**한다(첫 선택도 즉시 응답).

> **실측 (2026-07-13):** 사모사 사진 → 후보 `사모사`·`튀김만두`. 응답 8.5초(백그라운드는 응답을 막지 않음). 적재 결과 — `사모사`는 미등록이라 **llm 301kcal 신규 적재**, `튀김만두`는 이미 mfds에 있어 **LLM 미호출 스킵**.

> **개정 (2026-07-21, `docs/CKD_NUTRITION.md` 3-5):** 응답에 `sodium_mg`·`potassium_mg`·`phosphorus_mg`(nullable, DB 실측 그대로)가 **추가**됐다. 신장병 사용자가 **먹은 음식**의 수치를 확인하는 근거다. 등급(tier)은 **싣지 않는다** — 등급 판정은 질병 태그를 읽어야 해서 이 라우트의 동의 요건(Bearer만)이 `sensitive_health` 필수로 바뀌고, 미동의 사용자의 칼로리 조회까지 403이 되기 때문이다. 등급은 경고 API(16장)가 담당한다.

### 남은 과제

- 앱(`k-calAI-RN`)의 `source='llm'` 배지·503 처리 — API 계약 변경이므로 같은 작업 단위에서 반영한다.
- 사용자가 llm 행의 kcal을 수동 교정한 빈도는 그 추정이 나빴다는 가장 강한 신호다. 교정 로그를 재감수 큐로 쓰는 것은 후속 과제.

---

## 25. 운동 기록 (2026-07-21 확정 — 리비전 0020)

> 근거·설계는 **`docs/ACTIVITY_GUIDANCE.md` 3-2**가 정본이다. 여기에는 계약만 적는다.

**원칙: 앱과 웹은 같은 레벨의 서비스다.** 기록·조회·집계 API 는 전부 플랫폼 중립이고, 기기 연동(3단계)은
`source` 가 하나 느는 **입력 경로**일 뿐이다. 웹 사용자는 수동 입력으로 같은 기능을 계속 쓴다.

### `exercise_logs` (신규 테이블)

식단(`meal_logs`)과 같은 규약 — 하루 여러 건, 하루 경계는 **UTC 자정**, **soft delete**, 남의 것은 **404 존재 은닉**.

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `user_id` | FK users.id, index | ⚠️ **`account_service.delete_account` 삭제 연쇄와 `tests/test_account_service.py`의 `handled` 집합에 이미 추가함** |
| `performed_at` | timestamptz, index | 끼니 `logged_at`과 같은 규약(과거 날짜는 UTC 정오 앵커) |
| `exercise_type` | varchar(30) | `fitness_rules.EXERCISE_TYPES`의 키. 참조 테이블이 아니다 — MET 값이 코드에 있어야 해서 목록도 같은 곳에 둔다 |
| `duration_minutes` | int | 1~1440 |
| `intensity` | varchar(10) | `light`·`moderate`·`vigorous` — 보건복지부 지침의 강도 축과 일치 |
| `kcal` | int NULL | MET×체중×시간 산출값 또는 사용자 입력. **체중을 모르면 NULL**(지어내지 않는다) |
| `source` | varchar(20) default `'manual'` | `manual`·`healthkit`·`health_connect`. 3단계에서 스키마를 안 바꾸려고 미리 뒀다 |
| `memo` · `deleted_at` · `created_at` · `updated_at` | | |

복합 인덱스 `(user_id, performed_at)` — 날짜별 조회와 기간 집계가 주 질의다.

### API (전부 Bearer)

| 메서드 | 경로 | 비고 |
|---|---|---|
| `GET` | `/api/exercise-types` | 선택지(코드·라벨·기본 강도). 앱이 목록을 하드코딩하지 않게 서버가 준다 |
| `POST` | `/api/exercises` | **201**. `intensity` 생략 시 종류별 기본값, `kcal` 생략 시 서버 산출. 없는 종류는 400 |
| `GET` | `/api/exercises?date=` | 그날 목록(오름차순). 생략 시 오늘(UTC) |
| `PUT` | `/api/exercises/{id}` | **전체 교체**. `performed_at` 생략 시 기존 시각 유지(끼니 PUT과 같은 예외) |
| `DELETE` | `/api/exercises/{id}` | **204**, soft delete |
| `GET` | `/api/me/exercise-summary?start_date&end_date` | 기간 집계 + 권장 대비 |

**요약 응답의 핵심**: `equivalent_moderate_minutes = moderate + vigorous × 2` (**고강도 1분 = 중강도 2분**, KPAG).
이 값을 권장 하한(150분)과 대조해 `remaining_minutes`·`achieved`를 준다. 저강도는 **권장량 집계에 넣지 않는다**
(지침 기준). 근력운동은 분이 아니라 **날짜 수**로 센다(`strength_days` — 같은 날 두 번 해도 1일).

---

## 20. 요금제·일일 쿼터 · 가입 강화 (2026-07-14 확정 — 리비전 0014)

> 구현 범위: `plans`(참조 테이블) · `user_subscriptions`(회원 1:1) · `vision_usage_daily`(비전 카운터) 3테이블, `GET /api/plans` · `GET·PUT /api/me/subscription`, 그룹·펫·predict 한도 강제, 가입 시 약관 동의 필수화, SMS 실발송 연동. **결제(인앱결제) 연동은 이 범위 밖이다.**

### 요금제 (확정)

| code | label | 가격 | 비전 LLM/일 | 그룹 추가 인원 | 반려동물 | 소유 그룹 |
|---|---|---:|---:|---:|---:|---:|
| `lite` | Lite | **0원 (무료)** | **5** | 1 | 1 | 1 |
| `pro` | Pro | 5,000원 | **30** | 5 | 5 | 3 |
| `premium` | Premium | 10,000원 | **100** | 10 | 10 | 5 |

> Lite 비전 쿼터는 2026-07-16에 3 → **5**로 올렸다(리비전 0016, 22장). 0014는 fresh DB에 3을 넣고, 0016 UPDATE가 fresh·기존 DB 양쪽을 5로 수렴시킨다. 아래 본문의 `daily_vision_quota` 판정 로직은 값에 무관하게 동일하다.

- **`max_group_members`는 "본인(owner) 제외" 추가 인원이다.** 정원 = 이 값 + 1 (Lite 그룹은 총 2명).
- **`max_owned_groups`가 없으면 인원 한도가 무의미하다** — 그룹을 여러 개 만들어 우회할 수 있기 때문이다. 그래서 소유 그룹 개수도 요금제 한도다.
- Premium 100건/일 근거: Gemini flash 비전 1건 원가가 약 1원이라 100건×30일이라도 3,000원대(요금의 30%)이고, 실사용은 하루 끼니 3~5건 + 재촬영이라 사실상 무제한처럼 쓰인다.
- 요금제를 **코드 enum 이 아니라 참조 테이블**로 둔 이유는 10장 규칙 그대로다 — 가격·한도는 릴리즈 없이 조정돼야 하고, 앱이 목록을 그려야 한다.

### 테이블

| 테이블 | 컬럼 |
|---|---|
| `plans` | `code` `String(20)` PK · `label_ko` · `price_krw` · `daily_vision_quota` · `max_group_members` · `max_pets` · `max_owned_groups` · `sort_order` · `is_active` |
| `user_subscriptions` | `user_id` **PK**/FK(users) · `plan_code` FK(plans) · `started_at` · `updated_at` |
| `vision_usage_daily` | `user_id` + `usage_date` **복합 PK** · `used_count` · `updated_at` |

`user_subscriptions.user_id`를 PK로 둬서 **회원 1 : 요금제 1을 스키마로 강제**한다.

### 쿼터 리셋은 KST 자정

기록(`meal_logs`·`weight_logs`)의 하루 경계는 UTC지만, **쿼터는 KST(Asia/Seoul) 자정에 리셋**한다 — "오늘 몇 건 남았나"는 사용자가 체감하는 값이라 국내 서비스 기준시를 따라야 한다. `vision_usage_daily.usage_date`는 KST 날짜다 (`timeutil.today_kst()`). 서버 TZ 설정에 의존하지 않도록 고정 오프셋(+09:00)으로 둔다.

### 쿼터 차감은 원자적 UPSERT — 그리고 선차감·환불이다

```sql
INSERT INTO vision_usage_daily (user_id, usage_date, used_count) VALUES (:u, :d, 1)
ON CONFLICT (user_id, usage_date) DO UPDATE SET used_count = vision_usage_daily.used_count + 1
WHERE vision_usage_daily.used_count < :limit
RETURNING used_count
```

- `WHERE`가 거짓이면 갱신되는 행이 없어 **RETURNING이 비고, 그것이 곧 한도 초과 신호**다. 판정과 증가가 한 문장이라, 동시 요청이 각자 COUNT를 읽고 둘 다 통과하는 경합이 생기지 않는다.
- **Gemini 호출 전에 차감하고, 실패(503)하면 환불한다.** 성공 후 차감으로 미루면 동시 요청이 전부 한도를 통과한다. 먼저 잠그고, 사용자 잘못이 아닌 실패에만 되돌린다.
- 차감은 **업로드 검증을 통과한 뒤**다 — 형식 오류(413/415/400)로 실패한 요청이 쿼터를 먹으면 안 된다.
- `consume_vision_quota`는 `(사용량, 한도, **차감한 날짜**)`를 반환하고, **환불은 반드시 그 날짜로** 한다. 환불 시점에 `today_kst()`를 다시 부르면 자정을 걸친 요청(23:59 차감 → 00:00 실패)이 엉뚱한 날의 카운터를 깎는다.

### 그룹·펫 한도는 행 잠금으로 직렬화한다

비전 쿼터와 달리 그룹·펫 한도는 count-then-insert라 원자적이지 않다. `ensure_can_*`는 **소유자의 `user_subscriptions` 행을 `SELECT ... FOR UPDATE`로 잠근 뒤** 센다 (`get_user_plan(..., for_update=True)`). 잠금은 호출자의 commit까지 유지되므로 같은 소유자의 '추가'가 직렬화된다 — 없으면 동시 join 두 건이 둘 다 COUNT를 읽고 통과해 정원을 1 넘긴다.

### `is_active`는 "판매 중"이지 "구독 유효"가 아니다

- `get_plan()` — **기존 구독 해석용. `is_active`를 보지 않는다.** 여기서 활성 플랜만 반환하면, 요금제 하나를 판매 중단하는 순간 그 요금제를 쓰던 **기존 회원 전원의 요청이 깨진다**(predict는 500).
- `get_purchasable_plan()` — **새로 고르는 경로(가입·변경)용.** 판매 중단된 플랜은 선택할 수 없다.

### 402 Payment Required — 한도 초과의 단일 응답

`429`(레이트리밋, 기다리면 풀림)와 달리 **402는 "결제해야 풀린다"**는 뜻이다. `PlanLimitError`(서비스 레이어의 순수 예외)를 `main.py`의 **전역 예외 핸들러**가 변환한다 — 어느 라우트에서 나든 본문이 같아야 앱이 한 곳에서 업그레이드 화면으로 분기한다.

```jsonc
{
  "detail": "Lite 요금제는 반려동물을 1마리까지 등록할 수 있습니다. 요금제를 업그레이드해주세요.",
  "code": "plan_limit_exceeded",
  "resource": "pets",          // vision_daily | owned_groups | group_members | pets
  "plan": "lite",
  "limit": 1
}
```

`PlanLimitError`는 **`ValueError`를 상속하지 않는다** — 각 api 모듈의 `except ValueError → 400`에 잡히면 업그레이드 유도가 일반 입력 오류로 뭉개진다.

| 라우트 | 402가 나는 조건 | resource |
|---|---|---|
| `POST /api/predict` | 오늘 사용량 ≥ `daily_vision_quota` | `vision_daily` |
| `POST /api/groups` | 소유 그룹 수 ≥ `max_owned_groups` | `owned_groups` |
| `POST /api/groups/join` | (멤버 수 − 1) ≥ `max_group_members` | `group_members` |
| `POST /api/groups/{id}/pets` | 그룹 참여 펫 수 ≥ `max_pets` | `pets` |
| `POST /api/pets` | 소유 펫 수(`deleted_at IS NULL`) ≥ `max_pets` | `pets` |

### 그룹 자원은 **소유자의 요금제**로 판정한다

정원·펫 참여 한도는 참여자가 아니라 **그룹 owner의 플랜**을 본다 — 정원을 결제한 사람은 소유자다. 무료 회원도 Premium 소유자의 그룹에는 들어갈 수 있다.

### 다운그레이드 — 초과분은 유지하고 추가만 막는다

Pro에서 펫 3마리를 만든 뒤 Lite로 내려가도 **기존 3마리는 그대로 둔다.** 서버가 사용자가 만든 것을 말없이 지우지 않는다. 초과 상태에서는 '추가'만 402로 막힌다.

### API

| 메서드 | 경로 | 역할 | 인증 |
|---|---|---|---|
| `GET` | `/api/plans` | 요금제 목록 | **무인증** — 7장 Bearer 규약의 유일한 예외. 가격표는 비밀이 아니고, 가입 화면이 로그인 전에 그려야 한다 |
| `GET` | `/api/me/subscription` | 내 요금제 + 오늘 사용량 + `resets_at`(다음 KST 자정) | Bearer |
| `PUT` | `/api/me/subscription` | 요금제 변경. body `{plan_code}` | Bearer |

`POST /api/predict` 응답에 `vision_used` · `vision_limit`가 추가됐다 (앱이 별도 조회 없이 "오늘 2/3건"을 보여준다).

> **`PUT /api/me/subscription`은 결제 검증이 없다.** 인앱결제를 붙일 때 영수증 검증(App Store / Play Billing)을 통과한 뒤에만 `change_plan`을 호출하도록 좁혀야 한다. 지금은 누구나 Premium으로 바꿀 수 있다 — **이 상태로 운영 배포하면 안 된다.**

### 가입 강화 — 약관 동의 필수화

`POST /api/auth/signup/verify` 바디에 3개 필드가 추가됐다 (**로그인은 무변**):

```jsonc
{ "phone_number": "010...", "code": "123456",
  "agreed_terms": true, "agreed_privacy": true,   // 필수. 누락 422 / false 400
  "plan_code": "lite" }                            // 생략 시 무료 플랜
```

- 동의 검증은 **회원 행을 만들기 전**에 한다 — 미동의 요청이 인증번호만 소비하고 끝나면 안 된다.
- **회원·동의(`terms`·`privacy`)·구독이 한 트랜잭션**이다. 동의 없는 회원이나 요금제 없는 회원이 생기면 안 된다.
- 버전 상수는 `services/consent_service.py`의 `TERMS_VERSION`·`PRIVACY_VERSION`. 약관 문구를 고치면 여기를 올린다.
- 기존 회원은 0014가 전원 무료 플랜으로 백필한다. 조회 경로(`get_subscription`)에도 자기치유가 있어 구독 행이 없어도 500이 나지 않는다.

### SMS 실발송 (`services/sms_service.py`)

| 항목 | 결정 |
|---|---|
| 공급자 | **Solapi** (`SMS_PROVIDER=solapi`). 개인(비사업자) 가입 가능, 본인 명의 휴대폰 문자인증으로 발신번호 등록, SMS 18원/건 |
| **AWS SNS · Twilio는 후보가 아니다** | 한국은 AWS End User Messaging의 발신번호(long code·short code·sender ID)를 **하나도 지원하지 않는다.** 전기통신사업법 제84조의2가 요구하는 사전등록 발신번호를 확보할 방법이 없어 `[국제발신]`으로 나가고 통신 3사 스팸 필터에 걸린다 — **API는 200인데 사용자는 문자를 못 받는다.** 배포가 Lightsail이라는 이유로 SMS까지 AWS로 통일하면 안 된다 (발송은 어차피 HTTPS 아웃바운드다) |
| 발송 실패 | 방금 만든 코드 행을 **지운다**. 남기면 60초 쿨다운·시간당 한도(발급 이력 행을 센다)만 소진되어, 문자를 받지도 못한 사용자가 재요청까지 막힌다. api는 **503**(재시도 가능) |
| 트랜잭션 경계 | 코드 행을 **커밋한 뒤** 발송한다. 트랜잭션을 연 채 외부 HTTP(최대 5초)를 기다리면 공급자가 느려질 때마다 DB 커넥션·행 잠금이 붙잡혀 풀이 마른다 |
| provider 화이트리스트 | `SUPPORTED_SMS_PROVIDERS = {none, solapi}`. 오타(`solapy`)를 기동 시점에 막는다 — 안 막으면 서버는 뜨고 **모든 발송이 503**이 된다 |
| 개발 | `SMS_PROVIDER=none`(기본) — 발송하지 않고 인증번호가 `dev_code`로 응답에 나간다 |
| 운영 게이트 | `APP_ENV=production`이면 `SMS_PROVIDER=none`일 때 **기동 실패** (`ensure_production_sms_config`). 발송 경로가 없으면 아무도 가입할 수 없다 |
| 발신번호 유효기간 | Solapi 문자인증 등록번호는 **6개월**. 갱신하지 않으면 어느 날 전체 발송이 막힌다 (서류 제출 시 12개월) |

### 실측 (2026-07-14, 로컬)

가입(동의 2종 기록·lite 부여) → `GET /api/me/subscription` = `{used:0, limit:3, resets_at:"2026-07-15T00:00:00+09:00"}` / 펫 1마리 201 → 2마리째 **402** (`resource:"pets"`, `limit:1`) → `PUT /api/me/subscription` `pro` → 재시도 **201** / 사용량을 3으로 채운 뒤 `POST /api/predict` → **402** (`resource:"vision_daily"`, Gemini 미호출) / production 기동 게이트: `SMS_PROVIDER` 미설정·오타 모두 **기동 거부** 확인 / 회귀 테스트 `tests/test_subscription_service.py` 16건 포함 **67건 통과**.

### 남은 과제 (운영 배포 전 필수)

1. **인앱결제 연동** — `PUT /api/me/subscription`에 영수증 검증을 붙이기 전까지 유료 플랜은 사실상 무료다.
2. 쿼터 소진 알림(푸시)·월 사용량 집계는 범위 밖.

> **SMS 발송(Solapi)은 2026-07-14에 도입 직후 철회했다** — 인증을 카카오 로그인으로 교체했기 때문이다. 21장 참조.

---

## 21. 카카오 로그인 — SMS 인증 교체 (2026-07-14 확정 — 리비전 0015)

> 구현 범위: `users.kakao_id`·`nickname` · `kakao_link_codes` 테이블, `GET /api/auth/kakao/start`·`callback` · `POST /api/auth/kakao/login`·`signup`, 그룹 멤버 표시 교체, 탈퇴 시 카카오 연결 끊기. **휴대폰 OTP(SMS)와 `phone_verification_codes`·`services/sms_service.py`는 제거했다.**

### 왜 바꿨나 — 그리고 무엇을 잃었나

SMS(Solapi)를 붙였다가 **카카오 로그인으로 교체**했다. 인증 비용이 0원이고(SMS는 건당 18원), 전화번호는 이 서비스에서 **로그인 식별자와 그룹 멤버 표시 외에 쓰이는 곳이 없었다** — 알림 발송도, 본인확인도 하지 않는다. 즉 없어도 기능이 줄지 않는다.

**대신 무료 티어 어뷰징 방어를 잃었다.** 카카오계정은 **이메일 인증만으로 만들 수 있어**(휴대폰 인증은 카카오톡 앱 사용에 필요한 것이지 계정 생성 요건이 아니다) 회원번호를 새로 얻는 데 비용이 거의 없다. 즉 **Lite 3건/일은 계정을 갈아타면 우회된다.** 사람 단위로 묶을 수 있는 값은 CI뿐인데 사업자 정보가 등록된 비즈 앱만 신청할 수 있다.

이를 감수한 근거: 이 앱은 **기록이 쌓이는 앱**이라 계정을 버리면 끼니·추이·그룹·펫을 전부 잃는다. 우회의 실익이 있는 층은 "기록은 필요 없고 인식만 공짜로 쓰려는" 소수이며 어차피 유료 전환 대상이 아니다. **쿼터 방어가 실제로 필요해지면 카카오 계정 유일성이 아니라 서버 측(IP·디바이스 레이트리밋, 비용 상한)으로 해결한다.**

### 카카오 앱 등급별로 받을 수 있는 정보 (공식 문서 기준)

| 항목 | 요건 |
|---|---|
| **회원번호(`id`)** | 동의 없이 **항상 제공**. 우리의 로그인 식별자 |
| **닉네임 · 프로필 사진** | **일반(기본) 앱, 심사 없음** ← 지금 쓰는 범위 (`scope=profile_nickname`) |
| 카카오계정 이메일 | **비즈 앱** 전환 필요. 개인 개발자도 **본인인증만으로 전환 가능**, 심사 없음 |
| **전화번호 · CI** | 비즈 앱 **+ 개인정보 동의항목 심사**(영업일 3~5일). 카카오 공식 FAQ는 **"사업자 정보가 등록된 비즈앱만 신청 가능"**이라고 명시 → 개인 개발자 단계에서는 **설계에서 배제** |

### 흐름 — 서버가 코드를 교환하고, 앱에는 1회용 연동 코드를 준다

```
앱  →  GET /api/auth/kakao/start?platform=native|web    (expo-web-browser 로 연다)
서버 →  302 kauth.kakao.com/oauth/authorize?...&state=<서명값>
카카오 → GET /api/auth/kakao/callback?code=&state=       (서버가 받는다)
서버 →  코드 교환(client_secret) → /v2/user/me → **kakao_link_codes** 발급
서버 →  302 kcalairn://auth?code=<연동코드>&is_new=true|false   (웹은 /auth?...)
앱  →  POST /api/auth/kakao/{login|signup}  {link_code, ...}  → 세션 토큰
```

**왜 이렇게 도나 (셋 다 카카오의 제약이다):**

1. **커스텀 스킴(`kcalairn://`)은 카카오 Redirect URI 로 등록할 수 없다.** 카카오는 http/https만 받는다(불일치 시 `KOE006`). 그래서 콜백을 **서버가** 받고, 서버가 앱으로 딥링크를 되돌려준다.
2. **`client_secret` 이 사실상 필수**다(신규 REST 키는 기본 활성). 앱 번들에 시크릿을 넣으면 추출되므로 **토큰 교환은 반드시 서버**에서 한다. 그래서 앱에는 REST 키조차 필요 없다 — 서버 URL만 연다.
3. **카카오 인가 코드는 1회용**이다. 신규 회원은 약관 동의·요금제 선택을 거쳐야 가입이 완료되는데, 그 사이 인가 코드를 다시 쓸 수 없다. 그래서 콜백이 회원번호·닉네임을 담은 **1회용 연동 코드(TTL 10분)** 를 발급하고, 앱이 그걸로 로그인 또는 가입을 마무리한다.

**네이티브 카카오 SDK는 쓰지 않는다.** 얻는 건 카톡 앱-투-앱 UX뿐인데, 대가로 iOS/Android 네이티브 설정·키해시·Maven 저장소가 붙고 **웹 빌드에서 동작하지 않는다**(웹은 FastAPI가 서빙한다). REST 방식 하나로 앱·웹을 통일한다.

### 테이블

| 테이블 | 컬럼 |
|---|---|
| `users` (변경) | **`kakao_id`** `String(32)` UNIQUE (로그인 식별자) · **`nickname`** `String(50)` · `phone_number` → **nullable·유니크 해제** |
| `kakao_link_codes` (신규) | `code_hash` `String(64)` UNIQUE · `kakao_id` · `nickname` · `expires_at` · `consumed_at` · `created_at` |
| ~~`phone_verification_codes`~~ | **삭제** |

- **`phone_number` 컬럼은 남긴다.** 비즈 앱 전환 후 전화번호 동의항목을 받게 되면 다시 채울 자리이고, 기존 행의 값을 지우지 않기 위해서다. 신규 회원은 NULL이다.
- **연동 코드도 세션 토큰과 같이 해시만 저장한다.** 원문이 딥링크 URL에 실려 나가므로, DB 유출과 조합되면 안 된다.
- **기존 회원(0015 이전)은 삭제하지 않았다.** `kakao_id`가 NULL이라 로그인만 불가능하다.

### OAuth state — 서명값이라 테이블이 없다

CSRF 방어용 `state`는 `{platform, nonce, exp}`를 `AUTH_CODE_PEPPER`로 HMAC 서명한 값이다. 콜백이 우리가 시작시킨 요청인지, 어느 플랫폼(앱/웹)으로 돌려보낼지를 여기서 읽는다. 서명이 깨지거나 만료되면 **딥링크에 `error=invalid_state`를 실어 되돌린다** — 사용자를 브라우저에 갇히게 두지 않는다.

### API

| 메서드 | 경로 | 역할 | 인증 |
|---|---|---|---|
| `GET` | `/api/auth/kakao/start?platform=native\|web` | 카카오 인가 화면으로 302 | 무인증 |
| `GET` | `/api/auth/kakao/callback` | 카카오가 코드를 들고 오는 지점. **JSON이 아니라 리다이렉트로 답한다** (브라우저가 여는 화면이다). 실패도 딥링크에 `error=`를 실어 보낸다 | 무인증 |
| `POST` | `/api/auth/kakao/login` | body `{link_code}` → 세션 토큰. **미가입 계정은 404** (앱은 가입 화면으로) | 무인증 |
| `POST` | `/api/auth/kakao/signup` | body `{link_code, agreed_terms, agreed_privacy, plan_code?}` → 세션 토큰 | 무인증 |
| `POST` | `/api/auth/logout` | 기존과 동일 | Bearer |

- 동의는 **회원 행을 만들기 전에** 본다 — 미동의 요청이 연동 코드만 소비하고 끝나면 안 된다(그러면 카카오 로그인부터 다시 해야 한다).
- 회원·동의(`terms`·`privacy`)·구독은 **한 트랜잭션**이다 (20장과 동일).
- 로그인할 때마다 **닉네임을 카카오 값으로 갱신**한다 — 그룹 멤버에게 보이는 이름이다.

### 그룹 멤버 표시 — 마스킹 번호 → 닉네임

`GET /api/groups/{id}` 의 `members[].phone_number_masked`(`010****1234`)가 **`members[].nickname`** 으로 바뀌었다. 번호 자체가 없어졌기 때문이다. 프로필 동의를 거부해 닉네임이 없으면 `"이름 미설정"`을 준다. **앱 계약 변경이라 같은 작업 단위에서 앱도 고쳤다.**

### 회원 탈퇴 — 카카오 연결 끊기는 **의무**

카카오 공식 문서: *"서비스에서 탈퇴 … 시 서비스는 반드시 탈퇴 과정에 연결 해제 요청을 포함해야 합니다."*

- `POST https://kapi.kakao.com/v1/user/unlink` 를 **어드민 키** 방식(`target_id_type=user_id`)으로 부른다 — 카카오 액세스 토큰을 서버에 보관하지 않기 때문이다.
- **우리 쪽 파기를 커밋한 뒤에** 부르고, **실패해도 예외를 올리지 않는다.** 카카오 장애로 개인정보 파기(법정 의무)가 막히면 안 된다. 실패는 로그로 남겨 수동 정리한다.

### 환경변수

| 변수 | 필수 | 비고 |
|---|:---:|---|
| `KAKAO_REST_API_KEY` | 예 | 인가 URL에 실려 나가는 **공개값** |
| `KAKAO_CLIENT_SECRET` | 예 | **비밀값.** 신규 REST 키는 기본 활성이라 없으면 토큰 교환 실패 |
| `KAKAO_ADMIN_KEY` | 예 | **비밀값.** 탈퇴 시 unlink |
| `KAKAO_REDIRECT_URI` | 예 | 카카오 콘솔 등록값과 **문자 단위로 동일**해야 한다. 운영은 https 강제 |
| `APP_DEEPLINK_SCHEME` | 아니오 | 기본 `kcalairn` |

`APP_ENV=production`이면 위 4개가 없을 때 **기동 실패**한다(`ensure_production_kakao_config`) — 카카오가 유일한 인증 수단이라 설정이 없으면 아무도 로그인하지 못한다.

### 실측 (2026-07-14, 로컬)

`GET /api/auth/kakao/start` → `kauth.kakao.com/oauth/authorize?...&scope=profile_nickname&state=<서명값>` 302 확인 / 위조 state 콜백 → `kcalairn://auth?error=invalid_state` (브라우저에 갇히지 않음) / 동의 취소 → `error=cancelled` / 회귀 테스트: 카카오 인증 `tests/test_auth_service.py`(19건)·`tests/test_auth_api.py`(11건) 포함 **64건 통과**. **카카오 실호출 e2e는 콘솔에 Redirect URI 등록 후 수행해야 한다 (미완).**

### 남은 과제

1. **카카오 콘솔 설정** — Redirect URI 등록(`http://localhost:8000/api/auth/kakao/callback`, 운영은 https), 클라이언트 시크릿 생성, 어드민 키 확보. 이게 끝나야 실호출 e2e가 된다.
2. **연결 해제 웹훅** — 사용자가 카카오 [연결된 서비스 관리]에서 직접 끊으면 우리 DB가 모른다. 웹훅으로 동기화하는 것은 후속 과제.
3. 무료 티어 어뷰징 대응(IP·디바이스 레이트리밋)은 실제 남용이 관측되면 착수한다.

---

## 22. `/api/predict` 다중 음식 인식 · Lite 쿼터 5 (2026-07-16 확정 — 리비전 0016)

두 가지를 바꾼다. (1) Lite 무료 요금제의 일일 비전 쿼터를 3 → **5**로 올린다. (2) `/api/predict`가 **한 음식의 후보 나열**이 아니라 **사진에 있는 서로 다른 음식들**을 각각 돌려주도록 응답 계약을 바꾼다.

### Lite 쿼터 3 → 5 (리비전 0016)

- `alembic/versions/0016_lite_vision_quota_5.py` — `upgrade`는 `UPDATE plans SET daily_vision_quota = 5 WHERE code = 'lite'`, `downgrade`는 3으로 되돌린다.
- **0014의 시드는 건드리지 않는다.** 0014는 fresh DB에 3을 넣고, 0016이 그 뒤에서 5로 수렴시킨다. 이미 3이 적재된 기존 배포 DB도 이 UPDATE로 5가 된다 — 히스토리 재작성이 아니라 신규 리비전 체인이다.
- 판정 로직(`consume_vision_quota`, 원자적 UPSERT `WHERE used_count < limit`)은 값에 무관하게 동일하다. 20장 요금제 표를 5로 갱신했다.
- 회귀: `tests/test_subscription_service.py`의 `test_free_plan_allows_five_vision_calls_then_402`(5회 통과 후 6회째 402)·`test_upgrade_raises_the_daily_quota`(5 소진 후 pro 승격 시 6회째 통과)로 고정.

### `/api/predict` 응답 계약 — `predictions` → `foods`

기존 응답의 `predictions`(**한 음식의 후보들**)를 **`foods`(사진 속 서로 다른 음식들)**로 대체한다. 밥·국·반찬이 한 상에 있으면 각각 별도 항목이다.

```jsonc
// POST /api/predict (multipart: file 1장) 응답
{
  "foods": [
    { "label": "김치찌개", "score": 0.92, "portion_g": 250 },
    { "label": "쌀밥",     "score": 0.88, "portion_g": 210 }
  ],
  "vision_used": 2,
  "vision_limit": 5
}
```

- 각 항목: `label`(흔한 한글 요리명 — mfds/curated 매핑 유도), `score`(0~1 confidence), `portion_g`(int|null, 1인분 추정 g — **신규 필드**).
- **개수 상한 10** (`_MAX_FOODS`, `services/gemini_vision_service.py`). 폭주 응답이 prewarm 부하로 번지는 것을 막는다.
- **쿼터는 사진(호출)당 1건** 선차감/환불 그대로 — `foods` 개수와 무관하다. 음식 여러 개를 한 사진으로 한 번에 인식하는 것이 이 변경의 취지다.
- **음식 없음(빈 배열)** → `VisionError` → **503 + 쿼터 환불** (기존과 동일). 사용자 잘못이 아닌 실패에만 환불.
- 프롬프트도 "같은 음식의 후보 나열이 아니라 실제로 존재하는 서로 다른 음식을 각각" 반환하도록 바꿨다.

변경 파일: `schemas/predict_schema.py`(`Prediction`→`DetectedFood{label,score,portion_g}`, `PredictionResponse.predictions`→`foods`), `services/gemini_vision_service.py`(프롬프트·`_RESPONSE_SCHEMA{foods:[...]}`·`_MAX_FOODS`·`identify_food`가 portion_g 포함 반환), `api/predict_api.py`(반환 dict·로그·prewarm). prewarm은 인식된 **전 음식 라벨**을 예열한다(19장).

### 앱 계약 (같은 작업 단위에서 반영 필요)

`k-calAI-RN/services/calorie-api.ts`가 `data.predictions`를 읽으므로 **`foods`로 바꿔야** 한다(안 바꾸면 "predictions 배열이 없습니다"로 실패). `Prediction` 타입에 `portion_g?: number | null` 추가. 서버 계약만으로는 완결되지 않는 **크로스 레포 변경**이다.

---

## 23. 결제 내역 조회 API (읽기 전용, 리비전 0017 테이블 기반)

`payments` 테이블(`models/subscription_model.py`의 `Payment` — 리비전 0017)을 **읽기 전용으로 노출**한다. 청구(토스 빌링) 흐름은 아직 미구현이라 결제 데이터는 없다 — 조회 계약만 먼저 고정한다. **마이그레이션·스키마 변경 없음** (테이블은 이미 존재).

### API

| 메서드 | 경로 | 역할 | 인증 |
|---|---|---|---|
| `GET` | `/api/payments` | 내 결제 내역 (최신순, `created_at` desc → `id` desc) | Bearer |
| `GET` | `/api/payments/{id}` | 결제 1건 상세. **본인 것만** — 없거나 남의 것이면 **404**(존재 은닉) | Bearer |

`404` 규칙은 `meal_logs`·`pets`와 같다(남의 소유도 존재 자체를 숨긴다). 서비스 레이어는 `get_payment`에서 `LookupError`를 던지고 `api/payment_api.py`가 404로 변환한다. `LookupError` 메시지는 서비스가 만든 한국어 사용자 메시지라 그대로 노출한다(라이브러리 예외 `str(e)` 노출 금지 규칙과 무관).

### 응답 스키마 (`PaymentItem`)

```jsonc
// GET /api/payments → { "payments": [PaymentItem] }   (없으면 빈 배열)
// GET /api/payments/{id} → PaymentItem
{
  "id": 1,
  "order_id": "ord_...",
  "plan_code": "pro",
  "plan_label": "Pro",         // plans.label_ko 조회. 요금제 삭제·조회 실패 시 plan_code 로 폴백
  "amount": 5000,
  "status": "done",            // ready | done | failed | canceled (토스 어휘라 Literal 로 굳히지 않음)
  "method": "카드",            // nullable
  "approved_at": "2026-07-16T00:00:00Z",  // nullable
  "fail_reason": null,         // nullable
  "created_at": "2026-07-16T00:00:00Z"
}
```

- `payment_key`·`fail_code`는 응답에 **노출하지 않는다**(결제 게이트웨이 내부 식별자·코드). 사용자에게 필요한 필드만 내린다.
- `plan_label`은 `payment_service.payment_view`가 `plans`에서 조회한다(subscription_service 와 같은 조회 방식, 없으면 `plan_code` 폴백) — api 레이어는 조립하지 않는다.

### 앱 계약

`k-calAI-RN`에는 아직 `/api/payments` 소비처가 없다(결제 화면 미구현). 이 라우트는 앱 계약을 **깨지 않는 신규 추가**다. 결제/구독 관리 화면을 붙일 때 이 계약을 소비한다.

### 변경 파일

`schemas/payment_schema.py`(신규) · `services/payment_service.py`(신규) · `api/payment_api.py`(신규) · `main.py`(라우터 등록). `Payment` 모델·`payments` 테이블은 리비전 0017에서 이미 만들어졌다.

---

## 24. 토스페이먼츠 자동결제(빌링) (2026-07-16 확정 — 리비전 0017 테이블 기반)

> 구현 범위: `services/toss_client.py`(어댑터) · `services/billing_service.py`(흐름) · `api/billing_api.py`(3라우트) · 만료 강등(`subscription_service`) · `PUT /api/me/subscription` 유료 차단 · 갱신 배치. **마이그레이션 없음** — `billing_keys`·`payments`·`user_subscriptions` 확장 컬럼은 리비전 0017에 이미 있다. 23장(결제 내역 조회)이 이 장이 만든 데이터를 읽는다.

### 흐름

```
① POST /api/billing/checkout {plan_code}          Bearer
     └─ 유료·판매중 검증 → customerKey(uuid4) 발급 → {customer_key, client_key, plan_code, amount, order_name}
        (앱은 client_key + customer_key 로 토스 결제창을 띄운다. 서버는 아직 아무것도 기록하지 않는다)

② 토스 결제창 → 카드 등록 성공 → 앱이 authKey 수신

③ POST /api/billing/confirm {auth_key, customer_key, plan_code}    Bearer   ← **금액 필드가 없다**
     ├─ 플랜 검증 → amount = plans.price_krw            (서버가 정한다)
     ├─ toss: POST /v1/billing/authorizations/issue     → billingKey + card{company,number,cardType}
     ├─ billing_keys UPSERT (billing_key 는 EncryptedString 암호화 저장)
     ├─ payments INSERT (order_id=uuid4, status='ready') → **commit**
     ├─ toss: POST /v1/billing/{billingKey}             → paymentKey, method, approvedAt
     ├─ 성공: payments.status='done' + 구독 활성화(plan_code, active, period_end=+1개월, next_billing_at=period_end)
     └─ 실패: payments.status='failed'(fail_code·fail_reason) + **구독 미활성화** → 502

④ POST /api/billing/cancel                        Bearer
     └─ status='canceled', cancel_at_period_end=true, next_billing_at=null  (기간까지는 유료 유지)

⑤ scripts/charge_due_subscriptions.py (cron)
     └─ next_billing_at <= now 이고 해지 아님 → 청구
        성공: period_end·next_billing_at += 1개월 / 실패: past_due + 다음날 재시도
```

### 절대 규칙 (위반하면 돈이 샌다)

| 규칙 | 구현 |
|---|---|
| **금액은 서버가 정한다** | `confirm` 요청 스키마(`BillingConfirmRequest`)에 금액 필드가 **없다**. `plans.price_krw`만 쓴다 — 클라이언트가 보낸 금액을 받으면 100원짜리 Premium이 팔린다 |
| **시크릿 키·빌링키는 서버 전용** | `TOSS_SECRET_KEY`는 이 값만으로 임의 청구가 가능하고 `billingKey`는 그 회원 카드의 재청구 자격증명이다. 로그·응답·에러 메시지에 **절대** 넣지 않는다 (로그에는 결제사 **코드**만). 앱에 내려가는 키는 `client_key`(공개값)뿐 |
| **빌링키는 암호화 저장** | `BillingKey.billing_key`는 `crypto.EncryptedString`(AES-256-GCM). 청구 직전에만 복호화 |
| **멱등 — 갱신 배치** | `payments.order_id` UNIQUE + `_mark_payment_done`이 이미 `done`인 주문을 재반영하지 않는다(기간 이중 연장 방지). 갱신 배치는 성공 시 `next_billing_at`이 한 달 뒤로 밀려 같은 날 재실행해도 대상에서 빠진다. ⚠️ **이 둘은 `confirm`을 덮지 못한다** — 주문번호가 같아야 걸리는데 `confirm`은 호출마다 새 `order_id`를 만든다 |
| **멱등 — `confirm`** | **이미 낸 기간에 다시 청구하지 않는다** (`_is_duplicate_confirm`, 2026-07-16). 같은 플랜 + `active` + 기간이 남아 있으면 청구·토스 호출 없이 현재 구독을 **200**으로 돌려준다. 통과시키는 경우: 다른 플랜(업그레이드는 별개 결제) · `past_due`(카드 바꿔 재결제하려는 정당한 시도를 막으면 복구할 길이 사라진다) · `canceled`(재구독 의사표시) · 기간이 없거나 지난 경우 |
| **결제 실패 시 구독 미활성화** | 청구 예외가 나면 구독 행을 건드리지 않는다 — 결제 안 된 Pro가 생기면 안 된다 |
| **예외 원문 미노출** | `TossError.message`는 **우리가 만든 한국어 문구**다(토스 원문이 아니다). 원문·`fail_code`는 `error_logger`와 원장에만 남는다 |

### 중복 `confirm` — 상태로 막는다 (2026-07-16)

`confirm`은 **다시 들어온다**. 새로고침·뒤로가기(토스가 브라우저를 통째로 되돌려 만든 실제 URL이라 재마운트가 흔하다), 502·타임아웃 뒤 사용자의 재시도, 결제창 2회 완주가 전부 같은 결과를 낸다. 그런데 이 경로는 호출마다 새 `order_id`를 만들어 위 '멱등 — 갱신 배치'의 두 방어선이 **하나도 걸리지 않았다**. 남은 방어는 "토스가 authKey 재사용을 거절해 준다"뿐이었는데, 그건 **결제사에 위임된 것**이고 결제창을 두 번 완주하면 authKey가 서로 달라 그마저 통하지 않는다. 실측 결과 confirm 2회에 **5,000원이 두 번 청구되고 둘 다 `done`**, 기간은 연장이 아니라 `now+1개월`로 **재설정**됐다(= 산 날이 사라진다).

그래서 `_is_duplicate_confirm`이 청구 전에 판정한다. **주문번호가 아니라 구독 상태**가 기준이다 — "이미 이 플랜을 사서 기간이 남아 있는가".

**한계**: 게이트와 청구 사이에 토스 HTTP가 있어 구독 행을 잠근 채 통과할 수 없다(잠금을 쥔 채 결제사를 기다리면 커넥션 풀이 마른다 — 바로 아래 규약). 따라서 **완전히 동시에 도착한** confirm 둘은 여전히 각자 청구할 수 있다. 실제 재호출 경로는 전부 순차(사람이 결제창을 두 번 완주하는 데 최소 수 초, 첫 청구는 토스 왕복 ~1초)라 이 게이트가 막는다. 완전한 방어가 필요해지면 멱등성 키 테이블이 다음 수순이다.

앱은 이 변경으로 **더 안전해질 뿐 계약은 그대로다** — 응답 스키마가 같고, 중복 confirm이 502 대신 200을 준다(앱은 200을 성공으로 그린다). `k-calAI-RN/app/billing/success.tsx`의 서버 상태 되묻기는 이중 방어로 남는다.

### 원장(`payments`)이 먼저다

청구 **전에** `ready` 행을 만들고 **커밋한 뒤** 토스를 부른다. 이유 두 가지:
1. 외부 HTTP 중 프로세스가 죽어도 "청구를 시도했다"는 사실이 남는다(감사 근거).
2. 트랜잭션을 연 채 결제사(최대 10초)를 기다리면 DB 커넥션·행 잠금이 붙잡혀 풀이 마른다 — SMS 연동에서 얻은 규약(20장)과 같다.

`fail_code`(결제사 코드)는 원장·로그 전용이고, `fail_reason`에는 **사용자용 한국어 메시지**를 넣는다 — 23장 계약상 `fail_reason`은 `GET /api/payments`로 사용자에게 나가기 때문이다.

### 상태 전이 (`user_subscriptions.status`)

```
                confirm 성공          cancel              기간 만료(해석)
   (lite) ──────────────────→ active ──────→ canceled ──────────→ 실효 lite
                                 │  ↑                                  ↑
                    갱신 실패 ↓  │  │ 갱신 성공(재시도 포함)          │
                              past_due ────────────────────────────────┘
                        (다음날 재시도, 최대 기간종료+3일)
```

- `canceled`는 **즉시 해지가 아니다.** `current_period_end`까지 유료를 유지한다 — 이미 받은 돈의 이용권을 회수하지 않는다.
- `past_due`는 유예다. **기간을 줄이지 않고** 다음날 재시도한다. 재시도는 `current_period_end + BILLING_RETRY_MAX_DAYS`(3일)까지만 — 만료된 카드를 영원히 재시도하면 이미 lite로 강등된 회원 때문에 결제사만 매일 두드리게 된다.
- 결제수단이 없는 유료 구독(데이터 이상)은 `past_due` + `next_billing_at=null`로 두고 만료에 맡긴다.

### 만료 강등 — 행을 바꾸지 않고 **읽을 때 해석**한다

`subscription_service.get_effective_plan()`이 유료 플랜인데 `current_period_end < now`면 **lite로 해석해서** 반환한다. `plan_code`를 lite로 덮어쓰지 않는 이유:

1. 갱신 배치가 무엇을 청구해야 할지 잃는다.
2. "이 회원은 Pro였다"는 이력이 사라진다.
3. 만료를 감지한 첫 **읽기** 요청이 쓰기 트랜잭션을 여는 부작용이 생긴다.

강등이 `get_user_plan` 한 곳에 있으므로 **비전 쿼터·그룹 정원·펫 한도가 전부 자동으로 만료를 존중**한다. `my_subscription_view`도 같은 실효 플랜을 쓴다 — 화면의 쿼터 표시가 402 판정과 어긋나면 안 된다.

> **`current_period_end`가 `null`인 유료 구독은 만료 개념이 없다**(강등하지 않는다). 결제 이전에 부여된 구독 — 즉 `POST /api/auth/kakao/signup`의 `plan_code` 선택 — 이 여기 해당한다. **이건 남은 구멍이다** (아래 '남은 과제' 1번).

### 갱신 배치는 `get_plan`을 쓴다 (`get_purchasable_plan`이 아니다)

판매 중단된(`is_active=false`) 플랜이라도 **이미 구독 중인 회원의 갱신은 계속돼야 한다** — 20장의 `get_plan`/`get_purchasable_plan` 구분 그대로다. 구매 경로(`checkout`·`confirm`)만 `get_purchasable_plan`을 쓴다.

기간 계산은 **달력 인식**(`billing_service.add_one_month`, stdlib `calendar.monthrange`)이다. `timedelta(days=30)`을 쓰면 결제 기념일이 매달 밀린다(30일씩 12번이면 5일 어긋남). 말일은 클램프한다 — 1/31 + 1개월 = 2/28(윤년 2/29). 외부 의존(`dateutil`)은 들이지 않는다.

갱신 기준 시각은 **기존 `current_period_end`**다(now가 아니다) — 재시도로 이틀 늦게 성공해도 기념일이 밀리지 않는다. 다만 배치가 오래 멈췄다 돌아온 경우를 대비해, 계산된 기간이 과거면 미래가 될 때까지 민다(재청구 루프 방지).

### `PUT /api/me/subscription`은 이제 **무료로만** 바꿀 수 있다

유료 플랜으로의 변경은 **400 "결제를 통해 업그레이드해주세요"**다. 이 경로에는 결제 검증이 없어, 열어 두면 누구나 Premium으로 바꿀 수 있었다 (20장이 남긴 과제였다). 업그레이드는 `POST /api/billing/confirm`(실제 청구)을 거친다.

무료 전환은 **즉시** 적용되고 남은 유료 기간을 포기하며, 청구 상태(`current_period_end`·`next_billing_at`)를 비운다 — 남겨 두면 갱신 배치가 이미 무료인 회원을 청구 대상으로 집어 든다. **기간을 유지한 채 자동갱신만 끄려면 `/api/billing/cancel`**이다 — 유료 구독자에게는 그쪽이 정답이므로, 앱의 요금제 화면은 유료 구독자에게 PUT lite가 아니라 cancel을 붙여야 한다.

### API

| 메서드 | 경로 | 역할 | 실패 |
|---|---|---|---|
| `POST` | `/api/billing/checkout` | 결제창 값 발급 `{plan_code}` → `{customer_key, client_key, plan_code, amount, order_name}` | 400(무료·없는 플랜) · 401 · 503(키 미설정) |
| `POST` | `/api/billing/confirm` | 카드 등록 + 최초 청구 `{auth_key, customer_key, plan_code}` → `MySubscriptionResponse` | 400 · 401 · **502**(결제사 오류) · 503 |
| `POST` | `/api/billing/cancel` | 자동갱신 해지 (바디 없음) → `MySubscriptionResponse` | 400(무료 회원) · 401 |

전부 Bearer 필수. **502는 "우리 서버가 아니라 결제사 쪽 실패"**라 503(미구성)·400(사용자 입력)과 구분한다.

`MySubscriptionResponse`에 4필드가 **추가**됐다 (기존 필드는 불변 — 앱 계약을 깨지 않는 추가다):

```jsonc
{
  "plan": { ... },              // **실효 플랜** — 만료된 유료 구독은 lite 로 보인다
  "vision_usage": { ... },
  "started_at": "...",
  "status": "active",           // active | canceled | past_due
  "current_period_end": null,   // 유료 기간 종료(해지해도 이때까지는 유료)
  "next_billing_at": null,      // 다음 자동청구(해지·무료면 null)
  "cancel_at_period_end": false
}
```

### 환경변수

| 변수 | 필수 | 설명 |
|---|:---:|---|
| `TOSS_SECRET_KEY` | production 필수 | **비밀값.** Basic `base64("{키}:")` 인증. 없으면 `APP_ENV=production` 기동 실패, 개발에서는 빌링 라우트가 503 |
| `TOSS_CLIENT_KEY` | production 필수 | 공개값. 결제창 SDK 초기화용으로 앱에 내려간다 |
| `TOSS_TIMEOUT_SECONDS` | 아니오 | 기본 10 |

> 운영 서버에 **테스트 키(`test_sk_`)를 넣어도 기동은 된다** — 스테이징이 `APP_ENV=production`을 쓰기 때문에 접두어로 막지 않았다. 실결제 전환 시 키 교체를 체크리스트에 둘 것.

### 테스트

`tests/test_billing_service.py` **33건**(2026-07-16 중복 confirm 방어 5건 추가 — confirm 2회에 청구 1회·기간 미재설정·토스 미호출 · 업그레이드는 청구 · `past_due` 재결제는 청구 · 만료 후 재결제는 청구 · 해지 후 재구독은 청구). **토스 API는 호출하지 않는다** — `toss_client`의 `issue_billing_key`·`charge_billing`·`ensure_configured`를 monkeypatch로 대체한다(실제 호출은 테스트 키라도 결제사 트래픽이고, 네트워크에 의존하면 회귀가 아니게 된다). 커버: checkout 검증(무료·없는 플랜·키 미설정·customerKey 재사용) · confirm 성공(빌링키 **암호문** 저장을 원문 컬럼 조회로 확인 · payment done · 구독 활성화 · 기간 +1개월 · 서버 결정 금액) · confirm 청구 실패(payment failed · 구독 미활성화) · 멱등(배치 2회 실행 · done 주문 재반영 거부) · cancel(기간 유지 · 다음청구 null) · 만료 강등(`get_user_plan`→lite, 행 보존) · PUT 유료 차단 · 배치(연장 · past_due 재시도 · 재시도 창 만료 · 해지 건 제외 · 한 건 실패가 배치를 죽이지 않음) · 말일 클램프.

기존 `tests/test_subscription_service.py`는 유료 플랜 부여를 `change_plan` → `_grant_paid_plan`(결제 성공 후 상태를 직접 구성)으로 바꿨다 — 유료 전환이 막혔기 때문이며, 각 테스트의 의도(한도·판매중단·다운그레이드)는 그대로다.

`tests/test_toss_client.py` 8건 (2026-07-16 추가). 어댑터 자체에 테스트가 없어 **빌링키 로그 유출이 살아남았던** 자리다(아래 실측). 여기서도 토스는 호출하지 않는다 — 연결 실패는 **닫힌 로컬 포트**(127.0.0.1:9)로 만들고(가짜 예외를 던지는 monkeypatch로는 "requests가 URL을 메시지에 담는다"는 전제 자체를 검증할 수 없다), 그 밖은 `requests.post`를 대체한다. 커버: 연결 실패 시 빌링키·시크릿 미유출 + 진단(action·예외 타입)은 남음 · `TossError.__cause__`가 **끊겨 있음**(체인을 남기면 상위가 트레이스백을 찍는 순간 URL이 다시 샌다) · URL을 담은 임의 예외 메시지 미기록 · 4xx는 결제사 코드만 로깅 + 사용자에겐 우리 문구 · 미지 코드 폴백(코드는 원장용으로 보존) · non-json 응답 · Basic `base64("{키}:")` 규격 · 키 미설정 시 `TossNotConfiguredError`.

### 실측 (2026-07-16, 로컬)

`venv/bin/python -m pytest` **108건 통과**(기존 80 + 신규 28). `import main` OK. openapi: 3라우트 계약 확인(`BillingConfirmRequest`에 금액 필드 없음, `MySubscriptionResponse`에 4필드 추가). curl 실측 — 무토큰 401 / 유료 checkout(키 미설정) **503** / 무료 플랜 checkout **400** / 없는 플랜 **400** / `PUT /me/subscription` premium **400 "결제를 통해 업그레이드해주세요"** / lite **200** / 무료 회원 cancel **400** / confirm(키 미설정) **503**(토스 미호출). production 기동 게이트: 키 없음·한쪽만 있음 모두 **기동 거부**, 둘 다 있으면 기동. 로그 유출 검사: 결제사 400 응답을 흉내낸 호출에서 `error_log.txt`에 남은 것은 `status=400 code=REJECT_CARD_COMPANY`뿐이고 **시크릿 키·빌링키는 0건**, 사용자 메시지에 결제사 원문 미포함.

> ⚠️ **위 로그 유출 검사는 400 분기만 봤고, 그 범위 밖에 실제 유출이 있었다** (2026-07-16 발견·수정). `charge_billing`은 토스 규격상 빌링키를 **URL 경로**에 싣는데(`/v1/billing/{billingKey}`), `requests`의 연결 계열 예외(ConnectionError → MaxRetryError, SSLError 등)는 **메시지에 URL을 통째로 담는다**. 이를 `{error!r}`로 찍던 `_post`의 `except requests.RequestException` 분기에서 빌링키가 평문으로 `error_log.txt`와 journald에 남았다 — `BillingKey.billing_key`를 AES-256-GCM으로 암호화해 둔 것이 무의미해지는 유출이다(빌링키 하나면 그 회원 카드를 재청구할 수 있다). read timeout은 URL을 담지 않아 눈에 띄지 않았다.
>
> 수정: 예외 **타입 이름만** 로깅하고(`type(error).__name__` — action과 함께면 진단에 충분하다), `raise ... from None`으로 원인 체인을 끊는다(체인을 남기면 상위의 `logger.exception`·미처리 예외 경로로 같은 URL이 다시 샌다). `tests/test_toss_client.py`가 닫힌 포트로 이 속성을 건다 — 수정을 되돌리면 3건이 실패하는 것으로 유효성을 확인했다. 카나리아 빌링키가 로그에 0건.

### 재실측 (2026-07-16, 로컬 — 중복 confirm 방어 후)

`venv/bin/python -m pytest` **121건 통과**(108 + toss_client 8 + 중복 confirm 5). `import main` OK. 두 수정 모두 **테스트를 되돌려 유효성을 확인**했다 — 로그 유출 수정을 되돌리면 3건, 중복 게이트를 무력화하면 1건이 실패한다(로그에 `confirm ok`가 두 번 찍힌다).

curl 실측(중복 confirm): 구독을 `pro`·`active`·기간 한 달 남김으로 두고 소비된 authKey로 `POST /api/billing/confirm` → **200**(이전 502) + 현재 구독 반환, `payments` 신규 행 **0건**(= 청구 없음), 토스 미호출(키 미설정 환경인데도 200 — 게이트가 `issue_billing_key` 앞에서 걸러서 `ensure_configured`에 닿지 않는다).

### 남은 과제

1. **가입 시 유료 `plan_code` 선택이 결제 없이 그대로 부여된다** (`POST /api/auth/kakao/signup`). `current_period_end`가 null이라 만료 강등도 비켜간다 — 즉 **무료로 Premium을 얻는 경로가 남아 있다.** 이 장은 `PUT` 경로만 막았다(21장 계약·기존 테스트 변경을 피하려고). 가입을 lite 고정으로 좁히고 유료는 가입 후 `/api/billing/confirm`으로 유도하는 것이 정답이다.
2. **웹훅 미구현.** 토스 결제 상태 변경(취소·매입 실패)을 서버가 알 수 없다. 현재는 우리가 부른 청구의 응답만 원장에 반영한다.
3. **부분 환불·비례 배분(proration) 없음.** 업그레이드는 새 기간 1개월 전액 청구다.
4. **앱 화면 미구현** — `k-calAI-RN`에 `/api/billing/*` 소비처가 없다(결제창 SDK 연동 포함). 서버 계약만 먼저 고정했다.
5. 결제 실패 알림(푸시·메일)이 없다 — `past_due` 회원이 카드 교체 시점을 알 방법이 없다.
