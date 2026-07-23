"""하루 질환 축 누적 — 기준선이 근거대로 갈리는지 (docs/CKD_NUTRITION.md 3-6).

여기서 고정하려는 것은 계산이 아니라 **판단**이다.

- 나트륨만 상한(`limit_mg`)을 갖는다. 칼륨·인에 상한이 생기면 KDOQI 2020(혈청 수치 기반
  개인화)을 벗어난다.
- CKD 는 병기를 모르면 상한을 만들지 않는다. 임의로 고르면 투석 환자에게 과잉 제한이 된다.
- 실측이 없는 음식은 합계에서 빠지므로 `measured_items` 로 그 사실이 드러나야 한다.
"""

from datetime import datetime, timedelta

import pytest
from timeutil import UTC

from models.auth_model import User
from models.consent_model import UserCondition, UserHealthProfile
from models.health_model import FoodNutrition, MealItem, MealLog
from services import day_nutrition

TODAY = datetime.now(UTC).date()
NOON = datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC) + timedelta(hours=12)


@pytest.fixture
def user(db):
    row = User(kakao_id="day-nutrition-test", nickname="축테스터")
    db.add(row)
    db.flush()
    return row


def _add_condition(db, user, code: str) -> None:
    db.add(UserCondition(user_id=user.id, condition=code))
    db.flush()


def _set_stage(db, user, stage: str | None) -> None:
    db.add(UserHealthProfile(user_id=user.id, ckd_stage=stage))
    db.flush()


def _add_food(db, label: str, **nutrients) -> None:
    db.add(
        FoodNutrition(
            food_label=label,
            kcal_per_serving=nutrients.pop("kcal", 300),
            serving_desc="1인분",
            source="curated",
            **nutrients,
        )
    )
    db.flush()


def _log_meal(db, user, items: list[tuple[str, float]]) -> None:
    meal = MealLog(user_id=user.id, logged_at=NOON, meal_type="lunch", total_kcal=300)
    db.add(meal)
    db.flush()

    for label, ratio in items:
        db.add(
            MealItem(
                meal_log_id=meal.id,
                food_label=label,
                serving_ratio=ratio,
                kcal=300,
                source="manual",
            )
        )
    db.flush()


def _axis(result: dict, nutrient: str) -> dict:
    return next(axis for axis in result["axes"] if axis["nutrient"] == nutrient)


def test_no_condition_returns_none(db, user):
    """질환이 없으면 축 자체가 없다 — 홈은 지금까지처럼 칼로리만 보여준다."""
    _add_food(db, "테스트찌개ZZ", sodium_mg=1200)
    _log_meal(db, user, [("테스트찌개ZZ", 1.0)])

    assert day_nutrition.get_day_nutrient_axes(db, user.id, TODAY) is None


def test_hypertension_gets_sodium_limit(db, user):
    """고혈압은 병기 구분이 없어 단일 상한이 선다 (KSH2026 권고 21 — 2,000 mg)."""
    _add_condition(db, user, "hypertension")
    _add_food(db, "테스트찌개ZZ", sodium_mg=1200)
    _log_meal(db, user, [("테스트찌개ZZ", 1.0)])

    result = day_nutrition.get_day_nutrient_axes(db, user.id, TODAY)
    sodium = _axis(result, "sodium")

    assert sodium["consumed_mg"] == 1200.0
    assert sodium["limit_mg"] == 2000
    assert [axis["nutrient"] for axis in result["axes"]] == ["sodium"]


def test_serving_ratio_scales_the_total(db, user):
    """meal_items 에 영양소가 없어 조회 때 곱한다 — 반 인분은 절반이어야 한다."""
    _add_condition(db, user, "hypertension")
    _add_food(db, "테스트면ZZ", sodium_mg=1800)
    _log_meal(db, user, [("테스트면ZZ", 0.5)])

    result = day_nutrition.get_day_nutrient_axes(db, user.id, TODAY)

    assert _axis(result, "sodium")["consumed_mg"] == 900.0


def test_unmeasured_item_is_counted_but_not_summed(db, user):
    """실측 없는 음식은 합계에서 빠진다. 그 사실을 measured_items 로 드러내야 한다."""
    _add_condition(db, user, "hypertension")
    _add_food(db, "테스트국ZZ", sodium_mg=800)
    _log_meal(db, user, [("테스트국ZZ", 1.0), ("테스트미측정ZZ", 1.0)])

    result = day_nutrition.get_day_nutrient_axes(db, user.id, TODAY)

    assert result["total_items"] == 2
    assert _axis(result, "sodium")["measured_items"] == 1
    assert _axis(result, "sodium")["consumed_mg"] == 800.0


def test_ckd_without_stage_has_no_limit(db, user):
    """병기를 모르면 상한을 만들지 않는다 — 비투석 2,000 과 투석 3,000 중 하나를 임의로
    고르면 한쪽에게는 반드시 틀린 기준이 된다."""
    _add_condition(db, user, "ckd")
    _add_food(db, "테스트탕ZZ", sodium_mg=700, potassium_mg=300, phosphorus_mg=90)
    _log_meal(db, user, [("테스트탕ZZ", 1.0)])

    result = day_nutrition.get_day_nutrient_axes(db, user.id, TODAY)
    sodium = _axis(result, "sodium")

    assert sodium["limit_mg"] is None
    assert "투석 여부를 입력" in sodium["basis"]


def test_ckd_nondialysis_uses_2000(db, user):
    _add_condition(db, user, "ckd")
    _set_stage(db, user, "nondialysis")
    _add_food(db, "테스트탕ZZ", sodium_mg=700)
    _log_meal(db, user, [("테스트탕ZZ", 1.0)])

    result = day_nutrition.get_day_nutrient_axes(db, user.id, TODAY)

    assert _axis(result, "sodium")["limit_mg"] == 2000


def test_hemodialysis_relaxes_sodium_and_adds_references(db, user):
    """투석은 나트륨이 3,000 으로 완화되고, 칼륨·인에는 **참고치만** 붙는다."""
    _add_condition(db, user, "ckd")
    _set_stage(db, user, "hemodialysis")
    _add_food(db, "테스트과일ZZ", potassium_mg=426, phosphorus_mg=22, sodium_mg=1)
    _log_meal(db, user, [("테스트과일ZZ", 1.0)])

    result = day_nutrition.get_day_nutrient_axes(db, user.id, TODAY)
    potassium = _axis(result, "potassium")

    assert _axis(result, "sodium")["limit_mg"] == 3000
    # 상한이 아니라 참고치다. 이 둘이 뒤바뀌면 앱이 게이지를 그린다.
    assert potassium["limit_mg"] is None
    assert potassium["reference_mg"] == 2000
    assert _axis(result, "phosphorus")["reference_mg"] == 1000
    assert "혈액검사" in result["notice"]


def test_nondialysis_ckd_gets_no_potassium_reference(db, user):
    """비투석에 상시 칼륨 제한은 근거가 없다 (KSN1 서문 — 과도한 제한은 영양실조)."""
    _add_condition(db, user, "ckd")
    _set_stage(db, user, "nondialysis")
    _add_food(db, "테스트과일ZZ", potassium_mg=426)
    _log_meal(db, user, [("테스트과일ZZ", 1.0)])

    result = day_nutrition.get_day_nutrient_axes(db, user.id, TODAY)

    assert _axis(result, "potassium")["reference_mg"] is None
    assert _axis(result, "potassium")["consumed_mg"] == 426.0


def test_comorbidity_takes_the_stricter_limit(db, user):
    """투석(3,000) + 고혈압(2,000) 이면 더 엄격한 쪽을 쓴다."""
    _add_condition(db, user, "ckd")
    _add_condition(db, user, "hypertension")
    _set_stage(db, user, "hemodialysis")
    _add_food(db, "테스트면ZZ", sodium_mg=1800)
    _log_meal(db, user, [("테스트면ZZ", 1.0)])

    result = day_nutrition.get_day_nutrient_axes(db, user.id, TODAY)

    assert _axis(result, "sodium")["limit_mg"] == 2000


def test_diabetes_gets_sodium_axis_by_guideline(db, user):
    """당뇨의 dietary_tags 에는 나트륨이 없지만 1일 상한은 지침에 있다 (KDA2025 권고 9)."""
    _add_condition(db, user, "diabetes")
    _add_food(db, "테스트찌개ZZ", sodium_mg=1200)
    _log_meal(db, user, [("테스트찌개ZZ", 1.0)])

    result = day_nutrition.get_day_nutrient_axes(db, user.id, TODAY)

    assert _axis(result, "sodium")["limit_mg"] == 2300


def test_other_days_are_not_counted(db, user):
    """하루 경계는 끼니 조회와 같은 UTC 자정이다."""
    _add_condition(db, user, "hypertension")
    _add_food(db, "테스트찌개ZZ", sodium_mg=1200)
    _log_meal(db, user, [("테스트찌개ZZ", 1.0)])

    result = day_nutrition.get_day_nutrient_axes(db, user.id, TODAY - timedelta(days=1))

    assert result["total_items"] == 0
    assert _axis(result, "sodium")["consumed_mg"] == 0.0
