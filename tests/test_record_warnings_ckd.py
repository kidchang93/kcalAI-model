"""기록 경고의 신장병·고혈압 수치축 강화 — 실 DB 통합 (conftest db, 롤백).

docs/CKD_NUTRITION.md 3-3:
- 영양 제한 질병(ckd·hypertension)은 어느 영양소(nutrient)가 높은지까지 알려준다.
- 그 외 질병(diabetes)은 기존 키워드 경고(nutrient=None).
"""

import pytest

from models.auth_model import User
from models.consent_model import UserCondition
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
