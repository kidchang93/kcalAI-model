"""하루 질환 축 누적 — "오늘 나트륨 얼마나 먹었나"를 답한다.

경고(`nutrition_service.get_record_warnings`)는 **기록 확정 직전 그 순간**에만 보인다. 저장하고
나면 그 정보가 어디에도 남지 않아, 만성질환자에게 가장 중요한 숫자를 볼 화면이 없었다.
이 모듈이 그 공백을 메운다 — 같은 실측 데이터를 하루 단위로 합산한다.

**설계 원칙 세 가지**

1. **실측 조회는 경고와 같은 규약을 쓴다** (`nutrition_service.measured_nutrition_for`).
   두 곳이 다르게 찾으면 "경고는 떴는데 합계에는 안 잡히는" 음식이 생긴다.
2. **나트륨만 상한 대비이고 칼륨·인은 참고치다.** KDOQI 2020 은 칼륨·인을 혈청 수치 기반
   개인화로 두고 하루 mg 상한을 권고하지 않는다 (`ckd_food_rules` 하단 주석 · CKD_NUTRITION 3-6).
3. **못 센 항목 수를 숨기지 않는다.** 실측이 없는 음식(외국 요리·가공식품 일부)은 합계에서
   빠지므로 실제보다 적게 보인다. `measured_items`/`total_items` 를 함께 내려, 앱이 "5개 중
   3개 기준"이라고 밝힐 수 있게 한다. 이걸 감추면 커버리지 구멍이 "적게 먹었다"로 읽힌다
   (`PRODUCT_STRATEGY.md` §5-2 의 curated 결측 사건과 같은 종류의 실수).

영양소는 `meal_items` 에 저장되지 않는다(kcal 만 저장). 그래서 매 조회 시 food_label 로 실측
행을 찾아 `serving_ratio` 를 곱한다 — 저장을 늘리지 않는 대신, DB 값이 보정되면 과거 합계도
따라 바뀐다. 기록의 kcal 과 달리 이 수치는 **참고용 안내**라 그 편이 낫다고 판단했다.
"""

from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from timeutil import UTC
from models.consent_model import UserHealthProfile
from models.health_model import MealItem, MealLog
from services import chronic_food_rules, ckd_food_rules, meta_service, nutrition_service

# 축 정의는 CKD 모듈의 것을 그대로 쓴다 (tag, nutrient, label).
_AXES = ckd_food_rules.WARNING_AXES

# 나트륨 1일 상한을 가진 질환 (병기와 무관하게 단일 값). CKD 는 병기별이라 여기 없다.
_SODIUM_LIMIT_BY_CONDITION: dict[str, tuple[int, str]] = {
    "hypertension": (chronic_food_rules.HTN_SODIUM_MG_PER_DAY, "고혈압"),
    "diabetes": (chronic_food_rules.DM_SODIUM_MG_PER_DAY, "당뇨"),
}

# 하루 누적을 노출할 때 항상 함께 내리는 고지. 수치가 추정 기반이라는 사실과, 이것이 진료
# 기준이 아니라는 사실 두 가지를 말한다.
DAILY_NUTRIENT_NOTICE = (
    "표시되는 수치는 기록한 음식의 1인분 실측값을 합한 추정치입니다. "
    "목표량은 병기·검사 결과에 따라 다르니 의료진·영양사와 상담하세요."
)


def get_day_nutrient_axes(db: Session, user_id: int, target_date: date) -> dict | None:
    """오늘 먹은 음식의 질환 축 누적. 해당 질환이 없으면 None (앱은 카드를 그리지 않는다)."""
    axes = _axes_for_user(db, user_id)

    if not axes:
        return None

    items = _day_items(db, user_id, target_date)
    stage = get_ckd_stage(db, user_id)
    conditions = {condition.code for condition in meta_service.list_user_condition_types(db, user_id)}

    totals: dict[str, float] = {nutrient: 0.0 for nutrient in axes}
    measured_counts: dict[str, int] = {nutrient: 0 for nutrient in axes}

    for label, ratio in items:
        row = nutrition_service.measured_nutrition_for(db, label)

        if row is None:
            continue

        for nutrient in axes:
            value = getattr(row, f"{nutrient}_mg", None)

            if value is None:
                continue

            totals[nutrient] += float(value) * ratio
            measured_counts[nutrient] += 1

    payloads = [
        _axis_payload(nutrient, totals[nutrient], measured_counts[nutrient], conditions, stage)
        for nutrient in axes
    ]

    return {
        "axes": payloads,
        "total_items": len(items),
        "notice": _notice(payloads),
    }


def _notice(payloads: list[dict]) -> str:
    """고지문. 참고치를 하나라도 노출하면 그것이 지침 권고가 아니라는 사실을 덧붙인다."""
    if any(payload["reference_mg"] is not None for payload in payloads):
        return f"{DAILY_NUTRIENT_NOTICE} {ckd_food_rules.POTASSIUM_PHOSPHORUS_REFERENCE_NOTICE}"

    return DAILY_NUTRIENT_NOTICE


def get_ckd_stage(db: Session, user_id: int) -> str | None:
    """건강 프로필의 병기. 프로필 자체가 없으면 None — 없다고 조회가 실패하면 안 된다."""
    return db.scalar(
        select(UserHealthProfile.ckd_stage).where(UserHealthProfile.user_id == user_id)
    )


def _axes_for_user(db: Session, user_id: int) -> list[str]:
    """이 사용자에게 보여줄 영양 축. 질환의 dietary_tags 로 정하되 나트륨만 예외를 둔다."""
    tags: set[str] = set()
    codes: set[str] = set()

    for condition in meta_service.list_user_condition_types(db, user_id):
        tags.update(condition.dietary_tags)
        codes.add(condition.code)

    axes = [nutrient for tag, nutrient, _label in _AXES if tag in tags]

    # 당뇨의 dietary_tags 는 low_sugar·low_gi 라 나트륨 축이 안 잡히지만, 나트륨 1일 상한은
    # 지침에 있다(KDA2025 권고 9 — 2,300 mg). 태그가 아니라 근거를 따른다.
    if "sodium" not in axes and codes & _SODIUM_LIMIT_BY_CONDITION.keys():
        axes.insert(0, "sodium")

    return axes


def _day_bounds(target_date: date) -> tuple[datetime, datetime]:
    """끼니 조회(`health_service`)와 **같은 UTC 자정 경계**. 여기가 어긋나면 홈의 합계와
    기록 목록이 서로 다른 하루를 보게 된다."""
    start = datetime.combine(target_date, time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


def _day_items(db: Session, user_id: int, target_date: date) -> list[tuple[str, float]]:
    """그날 기록한 (음식명, 섭취 비율)."""
    start, end = _day_bounds(target_date)

    rows = db.execute(
        select(MealItem.food_label, MealItem.serving_ratio)
        .join(MealLog, MealLog.id == MealItem.meal_log_id)
        .where(
            MealLog.user_id == user_id,
            MealLog.deleted_at.is_(None),
            MealLog.logged_at >= start,
            MealLog.logged_at < end,
        )
    ).all()

    return [(label, float(ratio)) for label, ratio in rows]


def _axis_payload(
    nutrient: str,
    consumed_mg: float,
    measured_items: int,
    conditions: set[str],
    stage: str | None,
) -> dict:
    limit_mg, basis = _sodium_limit(conditions, stage) if nutrient == "sodium" else (None, None)
    reference_mg, reference_note = (
        _reference(nutrient, stage) if nutrient != "sodium" else (None, None)
    )

    return {
        "nutrient": nutrient,
        "label": ckd_food_rules.NUTRIENT_LABELS[nutrient],
        "consumed_mg": round(consumed_mg, 1),
        # 상한이 있으면 앱이 게이지를 그린다. 없으면 수치만 보여준다.
        "limit_mg": limit_mg,
        # 상한이 아니라 실무 참고치다. 게이지로 쓰지 않는다.
        "reference_mg": reference_mg,
        "basis": basis or reference_note,
        "measured_items": measured_items,
    }


def _sodium_limit(conditions: set[str], stage: str | None) -> tuple[int | None, str | None]:
    """나트륨 1일 상한 — 여러 질환이 겹치면 **더 엄격한 쪽**을 쓴다.

    CKD 는 병기가 있어야 값이 나온다(비투석 2,000 · 투석 3,000). 병기를 모르면서 다른 질환도
    없으면 상한 없이 안내 문구만 준다 — 임의로 한쪽을 고르면 투석 환자에게는 과잉 제한이고
    비투석 환자에게는 느슨하다.
    """
    candidates: list[tuple[int, str]] = [
        _SODIUM_LIMIT_BY_CONDITION[code] for code in conditions if code in _SODIUM_LIMIT_BY_CONDITION
    ]

    if "ckd" in conditions:
        ckd_limit = ckd_food_rules.sodium_daily_limit_mg(stage)

        if ckd_limit is not None:
            candidates.append((ckd_limit, f"신장 질환 {ckd_food_rules.CKD_STAGE_LABELS[stage]}"))
        elif not candidates:
            return None, ckd_food_rules.SODIUM_STAGE_UNKNOWN_NOTE

    if not candidates:
        return None, None

    limit_mg, source = min(candidates, key=lambda item: item[0])

    return limit_mg, f"{source} 기준 하루 {limit_mg:,} mg"


def _reference(nutrient: str, stage: str | None) -> tuple[int | None, str | None]:
    """칼륨·인의 실무 참고치. **투석 중일 때만** 준다 — 비투석에 상시 제한은 근거가 없다.

    KSN1 서문: 초기 CKD 에 과도한 제한은 오히려 영양실조를 부른다.
    """
    on_dialysis = stage in (
        ckd_food_rules.CKD_STAGE_HEMODIALYSIS,
        ckd_food_rules.CKD_STAGE_PERITONEAL,
    )

    if not on_dialysis:
        return None, None

    reference_mg = (
        ckd_food_rules.DIALYSIS_POTASSIUM_REFERENCE_MG
        if nutrient == "potassium"
        else ckd_food_rules.DIALYSIS_PHOSPHORUS_REFERENCE_MG
    )

    return reference_mg, f"투석 시 참고치 하루 {reference_mg:,} mg"
