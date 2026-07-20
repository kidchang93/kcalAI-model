"""식단 추천 서비스의 신장병 강화 로직 테스트 (DB 불필요 순수 부분).

- `_condition_tips`: 질병 태그 → 안내 문구.
- `_select_items`: 후보 행의 실측 영양값을 items dict 에 통과시키는지.
- `_filter_by_exclude_keywords`: 통과 항목이 영양 필드를 보존하는지.
(docs/CKD_NUTRITION.md 3-1)
"""

from decimal import Decimal
from types import SimpleNamespace

from services import recommendation_service as svc


def _condition(*tags: str) -> SimpleNamespace:
    return SimpleNamespace(dietary_tags=list(tags))


def _food(label: str, group: str, **nutrients) -> SimpleNamespace:
    base = {
        "food_label": label,
        "food_group": group,
        "kcal_per_serving": nutrients.get("kcal", 100),
        "sodium_mg": nutrients.get("sodium_mg"),
        "potassium_mg": nutrients.get("potassium_mg"),
        "phosphorus_mg": nutrients.get("phosphorus_mg"),
        "protein_g": nutrients.get("protein_g"),
    }
    return SimpleNamespace(**base)


class TestConditionTips:
    def test_ckd_all_three_axes(self):
        tips = svc._condition_tips([_condition("low_sodium", "low_potassium", "low_phosphorus")])
        joined = " ".join(tips)
        assert "나트륨" in joined
        assert "데친" in joined or "담" in joined  # 칼륨 저감 조리법
        assert "인이 높" in joined

    def test_non_ckd_condition_has_no_ckd_tips(self):
        # 당뇨(low_sugar)만 있으면 CKD 팁이 붙지 않는다.
        assert svc._condition_tips([_condition("low_sugar", "low_gi")]) == []

    def test_no_conditions(self):
        assert svc._condition_tips([]) == []


class TestSelectItemsNutrition:
    def test_nutrients_passed_through_as_float(self):
        pool = [
            _food("된장찌개", "찌개 및 전골류", sodium_mg=Decimal("820.5"),
                  potassium_mg=Decimal("310.0"), phosphorus_mg=Decimal("120.4"),
                  protein_g=Decimal("9.1"), kcal=180),
        ]
        items = svc._select_items(1, __import__("datetime").date(2026, 7, 20), "lunch", pool, [])
        assert len(items) == 1
        item = items[0]
        assert item["name"] == "된장찌개"
        assert item["sodium_mg"] == 820.5 and isinstance(item["sodium_mg"], float)
        assert item["potassium_mg"] == 310.0
        assert item["phosphorus_mg"] == 120.4
        assert item["protein_g"] == 9.1

    def test_missing_nutrients_become_none(self):
        pool = [_food("사과", "과일류", kcal=95)]  # 원물 — 영양값 NULL
        items = svc._select_items(1, __import__("datetime").date(2026, 7, 20), "snack", pool, [])
        assert items[0]["potassium_mg"] is None
        assert items[0]["protein_g"] is None

    def test_filter_preserves_nutrient_fields(self):
        candidate = {
            "name": "된장찌개", "kcal": 180, "reason": "r",
            "sodium_mg": 820.5, "potassium_mg": 310.0,
            "phosphorus_mg": 120.4, "protein_g": 9.1,
        }
        out = svc._filter_by_exclude_keywords([candidate], [], [])
        assert out[0]["potassium_mg"] == 310.0
        assert out[0]["protein_g"] == 9.1
