"""신장병 식이 규칙(services/ckd_food_rules.py) 순수 로직 테스트.

DB 불필요 — 대한신장학회 지침 분류가 라벨에 올바로 매칭되는지, 특히
1글자 토큰 오탐(김→김치, 무→무침, 배→배추)이 없는지 회귀 방어한다.
(docs/CKD_NUTRITION.md)
"""

from services import ckd_food_rules as r


class TestPotassiumTier:
    def test_high_potassium_vegetables_and_fruits(self):
        assert r.potassium_tier("시금치나물") == "high"
        assert r.potassium_tier("바나나") == "high"
        assert r.potassium_tier("토마토") == "high"
        assert r.potassium_tier("미역국") == "high"

    def test_low_potassium(self):
        assert r.potassium_tier("사과") == "low"
        assert r.potassium_tier("오이무침") == "low"  # 오이(저) — '무'(무침)에 오탐 안 함
        assert r.potassium_tier("배추된장국") == "low"  # 배추(저) — '배'(과일)에 오탐 안 함

    def test_dialysis_vs_nondialysis_fruit(self):
        # 포도·귤: 투석 기준 중칼륨, 비투석 기준 저칼륨 (KSN1 vs KSN2).
        assert r.potassium_tier("포도", on_dialysis=True) == "mid"
        assert r.potassium_tier("포도", on_dialysis=False) == "low"

    def test_unclassified_returns_none(self):
        assert r.potassium_tier("쌀밥") is None
        assert r.potassium_tier("된장찌개") is None

    def test_no_false_positive_from_dropped_single_char_tokens(self):
        # '김'(laver) 제거 → 김치/김밥/김국이 저칼륨으로 오탐되지 않는다.
        assert r.potassium_tier("김치찌개") is None
        assert r.potassium_tier("김밥") is None
        # '무'(radish) 제거 → 무 들어간 조리명이 저칼륨으로 오탐되지 않는다.
        assert r.potassium_tier("고등어무조림") is None


class TestPhosphorusAndSodium:
    def test_high_phosphorus(self):
        assert r.phosphorus_caution("치즈샐러드") == "치즈"
        assert r.phosphorus_caution("아몬드") == "아몬드"
        assert r.phosphorus_caution("현미밥") == "현미"
        assert r.phosphorus_caution("콜라") == "콜라"

    def test_protein_source_not_flagged_as_phosphorus(self):
        # 살코기·생선·달걀은 필수 단백질원이라 고인 목록에서 제외 — 끊으면 안 된다.
        assert r.phosphorus_caution("소고기구이") is None
        assert r.phosphorus_caution("고등어구이") is None
        assert r.phosphorus_caution("달걀찜") is None

    def test_high_sodium(self):
        assert r.sodium_caution("젓갈") == "젓갈"
        assert r.sodium_caution("라면") == "라면"
        assert r.sodium_caution("장아찌") == "장아찌"


class TestStageTargets:
    def test_protein_direction_reverses(self):
        # 비투석은 제한(0.6-0.8), 투석은 증량(1.2) — 방향이 반대다.
        assert r.stage_targets("nondialysis")["protein_g_per_kg"] == (0.6, 0.8)
        assert r.stage_targets("hemodialysis")["protein_g_per_kg"] == (1.2, 1.2)
        assert r.stage_targets("peritoneal")["protein_g_per_kg"][1] >= 1.2

    def test_sodium_limit_differs_by_stage(self):
        assert r.stage_targets("nondialysis")["sodium_mg_max"] == 2000
        assert r.stage_targets("hemodialysis")["sodium_mg_max"] == 3000

    def test_unknown_stage(self):
        assert r.stage_targets("unknown") is None
