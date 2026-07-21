"""기록 경고의 신장병·고혈압 수치축 강화 — 실 DB 통합 (conftest db, 롤백).

docs/CKD_NUTRITION.md 3-3:
- 영양 제한 질병(ckd·hypertension)은 어느 영양소(nutrient)가 높은지까지 알려준다.
- 그 외 질병(diabetes)은 기존 키워드 경고(nutrient=None).
"""

import pytest

from models.auth_model import User
from models.consent_model import UserCondition
from services import ckd_food_rules
from services.nutrition_service import get_record_warnings


def _user_with_condition(db, code: str, kakao: str) -> User:
    user = User(kakao_id=kakao, nickname=code)
    db.add(user)
    db.flush()
    db.add(UserCondition(user_id=user.id, condition=code))
    db.flush()
    return user


def _by_label(warnings, label):
    return [w for w in warnings if w["matched_label"] == label]


class TestCkdWarnings:
    def test_potassium_phosphorus_sodium_axes(self, db):
        user = _user_with_condition(db, "ckd", "warn-ckd")
        w = get_record_warnings(db, user.id, ["시금치나물", "젓갈", "치즈볶음", "고구마"])
        axes = {(x["matched_label"], x["nutrient"]) for x in w}
        assert ("시금치나물", "potassium") in axes
        assert ("젓갈", "sodium") in axes
        assert ("치즈볶음", "phosphorus") in axes
        assert ("고구마", "potassium") in axes  # 전분질 곡류 보강(STARCHY_K_HIGH)
        # 모든 ckd 경고는 nutrient 축과 code=ckd 를 가진다.
        assert all(x["code"] == "ckd" and x["nutrient"] is not None for x in w)

    def test_low_potassium_food_not_flagged(self, db):
        user = _user_with_condition(db, "ckd", "warn-ckd2")
        assert get_record_warnings(db, user.id, ["사과", "쌀밥"]) == []


class TestMeasuredAxis:
    """실측 수치 축 (docs/CKD_NUTRITION.md 3-5)."""

    def test_warning_carries_measured_value_and_tier(self, db):
        user = _user_with_condition(db, "ckd", "warn-measured")
        w = _by_label(get_record_warnings(db, user.id, ["시금치나물"]), "시금치나물")
        potassium = [x for x in w if x["nutrient"] == "potassium"]
        assert potassium, "시금치나물은 칼륨 축 경고가 나와야 한다"
        # 지침 이름 분류로 이미 high 다. 실측이 있으면 값도 함께 실린다.
        assert potassium[0]["tier"] == "high"
        assert potassium[0]["nutrient_mg"] is None or potassium[0]["nutrient_mg"] > 0

    def test_measured_high_flags_food_the_keyword_list_misses(self, db):
        # 이름 기반 지침 목록은 원물 중심이라 요리명을 놓친다 — 안동찜닭은 어떤 키워드에도
        # 걸리지 않지만 실측 칼륨이 3,000mg 대다(투석 하루 목표를 한 끼로 넘긴다).
        user = _user_with_condition(db, "ckd", "warn-measured2")
        label = "닭찜_안동찜닭"
        assert ckd_food_rules.potassium_high_match(label) is None, "이 테스트의 전제"

        w = [x for x in get_record_warnings(db, user.id, [label]) if x["nutrient"] == "potassium"]
        assert w, "실측이 높으면 이름에 안 걸려도 경고해야 한다"
        assert w[0]["tier"] == "high"
        assert w[0]["nutrient_mg"] > ckd_food_rules.POTASSIUM_TIER_HIGH_MG
        # 실측만으로 발동한 경고는 걸린 키워드가 없다.
        assert w[0]["matched_keyword"] == ""

    def test_unmeasured_food_keeps_name_based_warning(self, db):
        # DB 에 없는 라벨은 실측이 없다 — 이름 분류만으로 판정하고 수치는 None 이다.
        user = _user_with_condition(db, "ckd", "warn-measured3")
        w = [
            x
            for x in get_record_warnings(db, user.id, ["시금치듬뿍무침무침"])
            if x["nutrient"] == "potassium"
        ]
        assert w, "이름에 '시금치'가 있으면 실측이 없어도 경고한다"
        assert w[0]["nutrient_mg"] is None


class TestHypertensionWarnings:
    def test_sodium_only(self, db):
        user = _user_with_condition(db, "hypertension", "warn-htn")
        w = get_record_warnings(db, user.id, ["젓갈", "시금치나물"])
        # 고혈압은 low_sodium 만 → 나트륨 경고만, 칼륨(시금치)은 경고 안 함.
        assert [(x["matched_label"], x["nutrient"]) for x in w] == [("젓갈", "sodium")]


class TestNonNutrientConditionUnchanged:
    def test_diabetes_keeps_keyword_warning(self, db):
        user = _user_with_condition(db, "diabetes", "warn-dm")
        w = get_record_warnings(db, user.id, ["초콜릿케이크", "시금치나물"])
        # 당뇨는 영양 축이 없어 기존 키워드 경고(nutrient=None), 칼륨은 관여 안 함.
        assert len(w) == 1
        assert w[0]["matched_label"] == "초콜릿케이크"
        assert w[0]["nutrient"] is None
        assert w[0]["code"] == "diabetes"
