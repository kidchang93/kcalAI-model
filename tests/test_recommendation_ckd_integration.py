"""신장병 추천 강화 — 실 DB 통합 검증 (conftest db 픽스처, 종료 시 롤백).

로컬 개발 DB의 실제 식약처 음식 데이터로:
- 추천 item 에 실측 나트륨·칼륨·인·단백질이 실리는지 (식사는 83% 커버).
- 질병 tips(저염·칼륨 저감·인 주의)가 붙는지.
- 간식 후보 풀에서 고칼륨/고인 식품이 이름으로 사전 제거되는지 (docs/CKD_NUTRITION.md 3-2).
"""

from datetime import date

import pytest

from models.auth_model import User
from models.consent_model import UserCondition
from services import ckd_food_rules
from services.recommendation_service import get_recommendation

REC_DATE = date(2026, 7, 20)


@pytest.fixture
def ckd_user(db):
    user = User(kakao_id="ckd-integration-test", nickname="신장테스터")
    db.add(user)
    db.flush()
    db.add(UserCondition(user_id=user.id, condition="ckd"))
    db.flush()
    return user


def _contains_any(name: str, keywords) -> str | None:
    compact = name.replace(" ", "")
    for kw in keywords:
        if kw.replace(" ", "") in compact:
            return kw
    return None


class TestCkdRecommendationIntegration:
    def test_meal_items_carry_measured_nutrients(self, db, ckd_user):
        result = get_recommendation(db, ckd_user.id, REC_DATE, "lunch")
        assert result.cached is False
        assert len(result.items) > 0, "점심 후보가 비어서는 안 된다"
        # 식사 대분류는 칼륨·인이 83% 채워져 있어 최소 한 항목엔 실측값이 있어야 한다.
        assert any(item.get("potassium_mg") is not None for item in result.items)
        assert any(item.get("sodium_mg") is not None for item in result.items)
        for item in result.items:
            assert {"sodium_mg", "potassium_mg", "phosphorus_mg", "protein_g"} <= item.keys()

    def test_ckd_items_carry_display_tiers(self, db, ckd_user):
        # 신장병 사용자는 칼륨·인 등급이 실려야 한다 (docs/CKD_NUTRITION.md 3-4).
        result = get_recommendation(db, ckd_user.id, REC_DATE, "lunch")
        for item in result.items:
            assert "potassium_tier" in item
            assert "phosphorus_tier" in item
            assert item["potassium_tier"] in (None, "low", "mid", "high")
            assert item["phosphorus_tier"] in (None, "low", "mid", "high")
            # 실측값이 있으면 등급도 반드시 나온다 (수치만 있고 등급이 비는 카드가 없어야 한다).
            if item.get("potassium_mg") is not None:
                assert item["potassium_tier"] is not None

    def test_tiers_are_not_persisted_on_the_cached_row(self, db, ckd_user):
        # 등급은 응답에만 얹는다 — 질병이 바뀌면 저장된 등급이 거짓이 되기 때문 (tips 와 같은 정책).
        result = get_recommendation(db, ckd_user.id, REC_DATE, "dinner")
        assert all("potassium_tier" not in item for item in result.recommendation.items)

    def test_non_ckd_user_gets_no_tiers(self, db):
        user = User(kakao_id="plain-tier-test", nickname="일반등급")
        db.add(user)
        db.flush()
        result = get_recommendation(db, user.id, REC_DATE, "lunch")
        assert len(result.items) > 0
        assert all("potassium_tier" not in item for item in result.items)

    def test_ckd_tips_present(self, db, ckd_user):
        tips = get_recommendation(db, ckd_user.id, REC_DATE, "lunch").tips
        joined = " ".join(tips)
        assert "나트륨" in joined  # low_sodium
        assert ("데친" in joined) or ("담" in joined)  # low_potassium 조리법
        assert "인이 높" in joined  # low_phosphorus

    def test_snack_pool_excludes_high_potassium_and_phosphorus(self, db, ckd_user):
        result = get_recommendation(db, ckd_user.id, REC_DATE, "snack")
        for item in result.items:
            hit_k = _contains_any(item["name"], ckd_food_rules.POTASSIUM_HIGH_KEYWORDS)
            hit_p = _contains_any(item["name"], ckd_food_rules.HIGH_PHOSPHORUS_KEYWORDS)
            assert hit_k is None, f"고칼륨 간식이 추천됨: {item['name']} ({hit_k})"
            assert hit_p is None, f"고인 간식이 추천됨: {item['name']} ({hit_p})"

    def test_no_measured_high_potassium_or_phosphorus_leaks_any_meal(self, db, ckd_user):
        # 실측 칼륨·인 상한을 넘는 항목이 어느 끼니에도 새지 않아야 한다 (고구마 804·간 409 회귀 방어).
        for meal in ("breakfast", "lunch", "dinner", "snack"):
            result = get_recommendation(db, ckd_user.id, REC_DATE, meal)
            for item in result.items:
                k = item.get("potassium_mg")
                p = item.get("phosphorus_mg")
                assert k is None or k <= ckd_food_rules.POTASSIUM_SERVING_HIGH_MG, (
                    f"{meal}: 고칼륨 누수 {item['name']} K={k}"
                )
                assert p is None or p <= ckd_food_rules.PHOSPHORUS_SERVING_HIGH_MG, (
                    f"{meal}: 고인 누수 {item['name']} P={p}"
                )

    def test_excluded_reflects_ckd_condition(self, db, ckd_user):
        result = get_recommendation(db, ckd_user.id, REC_DATE, "dinner")
        excluded = result.recommendation.excluded
        codes = {e["code"] for e in excluded if e.get("type") == "condition"}
        assert "ckd" in codes

    def test_non_ckd_user_gets_no_tips_and_full_pool(self, db):
        user = User(kakao_id="plain-test", nickname="일반")
        db.add(user)
        db.flush()
        result = get_recommendation(db, user.id, REC_DATE, "snack")
        assert result.tips == []
        assert len(result.items) > 0
