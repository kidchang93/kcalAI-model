"""당뇨 식이 규칙 — 근거는 `docs/CHRONIC_NUTRITION_SOURCES.md` §2.

여기서 고정하려는 것은 계산이 아니라 **경계**다. 당뇨 규칙은 "무엇을 하는가"보다
**무엇을 하지 않는가**가 중요하다 — 지침이 유익하다고 명시한 음식을 경고하면
방향이 반대인 오류가 되고, 근거 없는 임계값은 처방에 근접한다.

1. 첨가당 경고는 **이름 축으로만** 발동한다 (총당류 실측으로 발동하면 생과일·흰우유가 걸린다).
2. 당류에는 **등급(tier)이 없다** — 간식·음료 행의 1인분이 제품 한 통·한 판이다.
3. 1인분으로 볼 수 없는 당류 수치는 경고 문장에 **근거로 붙이지 않는다**.
4. 당뇨에도 나트륨 축이 돈다 (KDA2025 권고 9, 리비전 0024).
"""

import pytest

from factories import make_user
from models.consent_model import UserCondition
from models.health_model import FoodNutrition
from services import chronic_food_rules, nutrition_service


@pytest.fixture
def diabetic(db):
    user = make_user(db, kakao_id="diabetes-rules-test", nickname="당뇨테스터")
    db.add(UserCondition(user_id=user.id, condition="diabetes"))
    db.flush()
    return user


def _add_food(db, label: str, *, sugar_g=None, sodium_mg=None, group=None):
    """실측 행을 이 테스트가 원하는 값으로 세운다.

    `food_label`이 unique 라, 공유 개발 DB 에 이미 있는 음식(사과·된장찌개 등)은 새로 넣지 않고
    **덮어쓴다**. 트랜잭션이 통째로 롤백되므로 원본은 그대로다 (`tests/conftest.py`).
    """
    row = db.query(FoodNutrition).filter(FoodNutrition.food_label == label).one_or_none()

    if row is None:
        row = FoodNutrition(
            food_label=label,
            kcal_per_serving=200,
            serving_desc="1인분",
            source="mfds",
        )
        db.add(row)

    row.sugar_g = sugar_g
    row.sodium_mg = sodium_mg
    row.potassium_mg = None
    row.phosphorus_mg = None
    row.food_group = group
    db.flush()


def _axes(warnings, label: str) -> set[str]:
    return {w["nutrient"] for w in warnings if w["matched_label"] == label}


# ── 1. 이름 축으로만 발동한다 ────────────────────────────────────────────────


@pytest.mark.parametrize("label", ["콜라", "오렌지주스", "초코도넛", "바닐라아이스크림"])
def test_added_sugar_sources_warn(db, diabetic, label):
    _add_food(db, label, sugar_g=25)

    warnings = nutrition_service.get_record_warnings(db, diabetic.id, [label])

    assert "sugar" in _axes(warnings, label)


@pytest.mark.parametrize("label", ["사과", "바나나", "우유", "토마토"])
def test_guideline_recommended_foods_never_warn(db, diabetic, label):
    """지침이 **유익하다고 명시한** 생과일·흰우유·채소는 총당류가 높아도 경고하지 않는다.

    이게 깨지면 규칙이 지침과 반대 방향으로 작동한다 (§2-2).
    """
    _add_food(db, label, sugar_g=30, group="과일류")

    warnings = nutrition_service.get_record_warnings(db, diabetic.id, [label])

    assert "sugar" not in _axes(warnings, label)


def test_zero_sugar_labels_are_exempt(db, diabetic):
    """'제로콜라'는 이름에 콜라가 들어 있어도 첨가당 급원이 아니다."""
    assert chronic_food_rules.added_sugar_caution("제로콜라") is None
    assert chronic_food_rules.added_sugar_caution("무가당요구르트") is None
    assert chronic_food_rules.added_sugar_caution("콜라") == "콜라"


@pytest.mark.parametrize(
    "label",
    ["사탕수수", "사탕무", "콜라비", "비콜라장어", "꿀풀", "리조또_스파이시 씨푸드 리조또"],
)
def test_substring_false_positives_stay_out(label):
    """부분 문자열 매칭의 오탐 — 운영 DB 식사·원물군 전수로 찾은 실제 라벨들이다.

    채소(사탕수수·콜라비·꿀풀)를 가당식품으로 경고하면 지침과 반대 방향이 된다.
    키워드를 늘릴 때 이 목록도 다시 확인해야 한다.
    """
    assert chronic_food_rules.added_sugar_caution(label) is None


def test_fruit_juice_is_still_flagged():
    """과즙은 뺄 수 없다 — 지침이 농축과즙을 첨가당으로 분류한다 (§2-2)."""
    assert chronic_food_rules.added_sugar_caution("배 과즙") is not None


# ── 2. 등급은 매기지 않는다 ─────────────────────────────────────────────────


def test_sugar_axis_has_no_tier(db, diabetic):
    """당류에 등급이 붙으면 안 된다 — 1인분 기준이 무너진 데이터 위의 등급은 거짓이다."""
    _add_food(db, "콜라", sugar_g=27)

    warnings = nutrition_service.get_record_warnings(db, diabetic.id, ["콜라"])
    sugar = [w for w in warnings if w["nutrient"] == "sugar"]

    assert sugar and all(w["tier"] is None for w in sugar)


# ── 3. 믿을 수 없는 1인분 수치는 근거로 붙이지 않는다 ──────────────────────────


def test_unrealistic_serving_sugar_is_dropped(db, diabetic):
    """케이크 한 판(당류 207 g)이 '1인분'으로 들어 있는 행 — 수치 없이 경고만 낸다."""
    _add_food(db, "케이크_생크림케이크 6호", sugar_g=207)

    warnings = nutrition_service.get_record_warnings(db, diabetic.id, ["케이크_생크림케이크 6호"])
    sugar = [w for w in warnings if w["nutrient"] == "sugar"]

    assert sugar, "이름 축(케이크)으로는 경고가 나와야 한다"
    assert all(w["nutrient_mg"] is None for w in sugar)


def test_realistic_serving_sugar_is_kept_with_unit(db, diabetic):
    _add_food(db, "콜라", sugar_g=27)

    warnings = nutrition_service.get_record_warnings(db, diabetic.id, ["콜라"])
    sugar = next(w for w in warnings if w["nutrient"] == "sugar")

    assert sugar["nutrient_mg"] == 27.0
    # 당류만 g 다 — 앱이 mg 로 표기하면 27,000 mg 짜리 콜라가 된다.
    assert sugar["nutrient_unit"] == "g"


def test_other_axes_stay_in_mg(db, diabetic):
    _add_food(db, "된장찌개", sodium_mg=1200)

    warnings = nutrition_service.get_record_warnings(db, diabetic.id, ["된장찌개"])
    sodium = next(w for w in warnings if w["nutrient"] == "sodium")

    assert sodium["nutrient_unit"] == "mg"


# ── 4. 당뇨에도 나트륨 축이 돈다 (리비전 0024) ───────────────────────────────


def test_diabetes_gets_sodium_axis(db, diabetic):
    """KDA2025 권고 9. 태그가 없던 동안 당뇨 사용자는 나트륨 경고를 전혀 못 받았다."""
    _add_food(db, "라면국물", sodium_mg=1557)

    warnings = nutrition_service.get_record_warnings(db, diabetic.id, ["라면국물"])
    sodium = [w for w in warnings if w["nutrient"] == "sodium"]

    assert sodium and sodium[0]["tier"] == "high"


# ── 5. 고지문 ───────────────────────────────────────────────────────────────


def test_sugar_warning_carries_limit_notice(db, diabetic):
    """등급이 없는 대신 GI·식이섬유 한계를 고지한다 (§2-4)."""
    _add_food(db, "콜라", sugar_g=27)

    response = nutrition_service.get_record_warnings_response(db, diabetic.id, ["콜라"])

    assert chronic_food_rules.DIABETES_LIMIT_NOTICE in (response["notice"] or "")


def test_no_warning_means_no_notice(db, diabetic):
    _add_food(db, "현미밥", sugar_g=1, sodium_mg=5)

    response = nutrition_service.get_record_warnings_response(db, diabetic.id, ["현미밥"])

    assert response["notice"] is None


# ── 6. 판정하지 못한 음식은 침묵하지 않는다 ─────────────────────────────────


def test_unmeasured_food_is_reported(db, diabetic):
    """실측도 없고 키워드에도 없으면 경고가 안 나간다 — 그 사실을 밝혀야 한다.

    이게 없으면 화면에서 "경고 없음"과 "안전함"이 구분되지 않는다.
    """
    _add_food(db, "돈까스테스트ZZ", sugar_g=None, sodium_mg=None)

    response = nutrition_service.get_record_warnings_response(db, diabetic.id, ["돈까스테스트ZZ"])

    assert response["warnings"] == []
    assert "돈까스테스트ZZ" in response["unmeasured"]


def test_measured_food_is_not_reported_as_unmeasured(db, diabetic):
    _add_food(db, "현미밥테스트ZZ", sodium_mg=5)

    response = nutrition_service.get_record_warnings_response(db, diabetic.id, ["현미밥테스트ZZ"])

    assert response["unmeasured"] == []


def test_warned_food_is_not_also_unmeasured(db, diabetic):
    """경고가 나간 음식은 판정된 것이다 — 두 번 말하지 않는다."""
    _add_food(db, "콜라", sugar_g=27, sodium_mg=10)

    response = nutrition_service.get_record_warnings_response(db, diabetic.id, ["콜라"])

    assert response["warnings"]
    assert "콜라" not in response["unmeasured"]


def test_no_condition_means_no_unmeasured_noise(db):
    """질환이 없으면 판정할 축도 없다 — 굳이 알릴 것이 없다."""
    user = make_user(db, kakao_id="no-condition-test", nickname="무질환")
    _add_food(db, "돈까스테스트ZZ", sodium_mg=None)

    response = nutrition_service.get_record_warnings_response(db, user.id, ["돈까스테스트ZZ"])

    assert response["unmeasured"] == []
