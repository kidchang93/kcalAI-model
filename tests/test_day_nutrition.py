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
from models.health_model import FoodNutrition
from services import day_nutrition, health_service

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
    """실제 저장 경로로 기록한다 — 영양 스냅샷이 그때 굳는다 (리비전 0025).

    `MealItem`을 직접 만들면 스냅샷이 비어 합계가 0이 된다. 하루 누적은 이제 그 스냅샷을
    읽으므로, 테스트도 앱과 같은 경로를 타야 실제 동작을 검증한다.
    """
    health_service.create_meal(
        db,
        user_id=user.id,
        meal_type="lunch",
        logged_at=NOON,
        photo_s3_key=None,
        items=[
            {
                "food_label": label,
                "serving_ratio": ratio,
                "kcal": 300,
                "source": "manual",
                "confidence": None,
            }
            for label, ratio in items
        ],
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
    """스냅샷은 **먹은 양 기준**으로 굳는다 — 반 인분은 절반이어야 한다."""
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


class TestAxisIntegrity:
    """축을 늘렸을 때 **조용히 틀리지 않는지**. 2026-07-25 실측 회귀 두 건.

    경고 축(`ckd_food_rules.WARNING_AXES`)에 당류를 더했더니, 이 모듈이 그 목록을 그대로
    참조하고 있어서 하루 누적에도 딸려 들어갔다. 그리고 둘 다 예외 없이 조용히 틀렸다 —
    합계는 항상 0이 됐고(컬럼이 sugar_g 라 `{nutrient}_mg` 조회가 빗나갔다), 참고치는
    "칼륨이 아니면 인"으로 갈라져 **당류에 인의 투석 참고치**가 붙어 나갔다.
    """

    def test_daily_axes_are_not_the_warning_axes(self):
        """두 목록은 분리돼 있어야 한다 — 요구하는 근거의 수준이 다르다."""
        from services import ckd_food_rules

        daily = {nutrient for _tag, nutrient, _label in day_nutrition._AXES}
        warning = {nutrient for _tag, nutrient, _label in ckd_food_rules.WARNING_AXES}

        assert daily == {"sodium", "potassium", "phosphorus"}
        # 경고에만 있는 축(당류)은 하루 누적에 들어오지 않는다.
        assert "sugar" in warning and "sugar" not in daily

    def test_every_daily_axis_has_a_column(self):
        """축마다 실측 컬럼이 있어야 한다. 없으면 합계가 조용히 0이 된다."""
        from models.health_model import FoodNutrition

        for _tag, nutrient, _label in day_nutrition._AXES:
            column = day_nutrition._AXIS_COLUMNS[nutrient]
            assert hasattr(FoodNutrition, column), f"{nutrient} → {column} 컬럼이 없다"

    def test_unknown_axis_raises_instead_of_zero(self, db, user):
        """모르는 축은 터져야 한다 — 0으로 집계되면 아무도 알아채지 못한다."""
        _add_food(db, "테스트당류ZZ", sodium_mg=100)

        with pytest.raises(KeyError):
            day_nutrition._AXIS_COLUMNS["sugar"]

    def test_reference_is_never_defaulted(self):
        """참고치는 아는 축에만 준다. 기본값으로 흘리면 없는 기준이 만들어진다."""
        for nutrient in ("sugar", "carbs", "protein"):
            reference_mg, note = day_nutrition._reference(nutrient, "hemodialysis")

            assert reference_mg is None, f"{nutrient} 에 참고치가 붙었다"
            assert note is None

    def test_known_references_still_work(self):
        potassium, _ = day_nutrition._reference("potassium", "hemodialysis")
        phosphorus, _ = day_nutrition._reference("phosphorus", "hemodialysis")

        assert potassium == 2000
        assert phosphorus == 1000


class TestSnapshotIsImmutable:
    """기록은 기록이어야 한다 (리비전 0025).

    예전에는 하루 누적이 `food_label`로 `food_nutrition`을 매번 다시 조회해 합쳤다. 그래서
    **DB 값이 바뀌면 과거 기록이 말하는 수치도 소급해 바뀌었다.** 2026-07-25에 1인분 기준을
    4,536행 고치고 동명 행 규칙도 바꿨을 때 실제로 일어난 일이다.

    진료에서 되짚거나 검사 수치 악화의 원인을 찾으려면 그때의 근거가 그대로 있어야 한다
    (`docs/PRODUCT_STRATEGY.md` §0-1·§0-2).
    """

    def test_later_db_change_does_not_rewrite_the_past(self, db, user):
        _add_condition(db, user, "hypertension")
        _add_food(db, "테스트국ZZ", sodium_mg=800)
        _log_meal(db, user, [("테스트국ZZ", 1.0)])

        before = _axis(day_nutrition.get_day_nutrient_axes(db, user.id, TODAY), "sodium")

        # 임포트·보정 스크립트가 값을 고치는 상황 (오늘 4,536행에 실제로 일어났다).
        row = db.query(FoodNutrition).filter(FoodNutrition.food_label == "테스트국ZZ").one()
        row.sodium_mg = 2500
        db.flush()

        after = _axis(day_nutrition.get_day_nutrient_axes(db, user.id, TODAY), "sodium")

        assert before["consumed_mg"] == 800.0
        assert after["consumed_mg"] == 800.0, "이미 기록된 끼니가 나중 DB 값으로 바뀌면 안 된다"

    def test_new_record_uses_the_new_value(self, db, user):
        """반대로 **새 기록**은 고쳐진 값을 쓴다 — 스냅샷은 동결이지 무시가 아니다."""
        _add_condition(db, user, "hypertension")
        _add_food(db, "테스트국ZZ", sodium_mg=800)

        row = db.query(FoodNutrition).filter(FoodNutrition.food_label == "테스트국ZZ").one()
        row.sodium_mg = 2500
        db.flush()

        _log_meal(db, user, [("테스트국ZZ", 1.0)])

        result = day_nutrition.get_day_nutrient_axes(db, user.id, TODAY)

        assert _axis(result, "sodium")["consumed_mg"] == 2500.0
