"""체성분·활동 규칙 단위 검증 (docs/ACTIVITY_GUIDANCE.md).

경계값이 어긋나면 사용자가 잘못된 분류를 본다 — 특히 한국 기준(23·25)과 WHO 기준(25·30)의
혼동은 실제로 자주 나는 실수라 경계를 못 박아 둔다.
"""

from services import fitness_rules as f


class TestBmi:
    def test_calculation(self):
        # 170cm 68kg → 68 / 1.7² = 23.529... → 23.5
        assert f.calculate_bmi(170.0, 68.0) == 23.5

    def test_missing_or_invalid_input(self):
        assert f.calculate_bmi(None, 60.0) is None
        assert f.calculate_bmi(170.0, None) is None
        assert f.calculate_bmi(0.0, 60.0) is None
        assert f.calculate_bmi(170.0, -1.0) is None

    def test_korean_boundaries_not_who(self):
        # 한국(대한비만학회) 기준: 23 비만 전단계, 25 1단계 비만.
        # WHO 기준(25 과체중·30 비만)을 쓰면 아래가 전부 깨진다.
        assert f.bmi_category(18.4) == "underweight"
        assert f.bmi_category(18.5) == "normal"
        assert f.bmi_category(22.9) == "normal"
        assert f.bmi_category(23.0) == "pre_obese"
        assert f.bmi_category(24.9) == "pre_obese"
        assert f.bmi_category(25.0) == "obese_1"
        assert f.bmi_category(29.9) == "obese_1"
        assert f.bmi_category(30.0) == "obese_2"
        assert f.bmi_category(34.9) == "obese_2"
        assert f.bmi_category(35.0) == "obese_3"

    def test_category_none(self):
        assert f.bmi_category(None) is None
        assert f.bmi_category_label(None) is None

    def test_labels_are_korean(self):
        assert f.bmi_category_label("normal") == "정상"
        assert f.bmi_category_label("obese_1") == "1단계 비만"
        # 모든 분류에 라벨이 있어야 한다 — 하나라도 빠지면 화면에 빈칸이 나온다.
        for code in ("underweight", "normal", "pre_obese", "obese_1", "obese_2", "obese_3"):
            assert f.bmi_category_label(code)


class TestActivityGuide:
    def test_adult(self):
        guide = f.activity_guide(35)
        assert guide["moderate_min_minutes"] == 150
        assert guide["moderate_max_minutes"] == 300
        assert guide["vigorous_min_minutes"] == 75
        assert guide["vigorous_max_minutes"] == 150
        assert guide["strength_days"] == 2
        # 평형성은 노인 전용 축이라 성인에게는 없다.
        assert guide["balance_days"] is None
        assert guide["is_senior"] is False

    def test_senior_has_lower_vigorous_cap_and_balance(self):
        guide = f.activity_guide(65)
        # 노인은 고강도 상한이 낮다 (150 → 100분).
        assert guide["vigorous_max_minutes"] == 100
        assert guide["balance_days"] == 3
        assert guide["is_senior"] is True
        assert any("평형성" in tip for tip in guide["tips"])

    def test_senior_boundary(self):
        assert f.activity_guide(64)["is_senior"] is False
        assert f.activity_guide(65)["is_senior"] is True

    def test_unknown_age(self):
        assert f.activity_guide(None) is None
        assert f.activity_guide(-1) is None

    def test_notice_states_not_a_medical_device(self):
        # Google Play 건강 앱 정책·책임 경계상 이 문구는 빠지면 안 된다 (ACTIVITY_GUIDANCE §4).
        notice = f.activity_guide(30)["notice"]
        assert "의료기기가 아니" in notice
        assert "의료진" in notice

    def test_source_is_cited(self):
        assert "보건복지부" in f.activity_guide(30)["source"]
