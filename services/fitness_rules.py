"""체성분·신체활동 규칙 — 공신력 있는 지침을 코드화한 단일 근거 모듈.

BMI 판정과 권장 신체활동량을 여기 한 곳에만 둔다. `ckd_food_rules.py`와 같은 성격이다.

출처 (전부 무료 공개 자료):
- 대한비만학회 「비만 진료지침 2022(8판)」 — BMI 분류(한국/아시아-태평양 기준), 허리둘레 기준.
- 보건복지부 「한국인을 위한 신체활동 지침서」(2023 개정판) · 질병관리청 국가건강정보포털 '신체활동'
  — 성인/노인 주당 권장 유산소·근력·평형성, 좌식시간 권고.
- WHO Guidelines on physical activity and sedentary behaviour (2020) — 국제 표준(대조용).

⚠️ 이것은 **처방이 아니라 지침의 일반 권고**다. 개인의 적정 활동량·체중은 질환·복약·체력에 따라 달라지며
의료진 상담이 필요하다. 사용자 노출 시 항상 고지문을 붙인다 (docs/ACTIVITY_GUIDANCE.md §4).

⚠️ BMI 기준은 **한국(아시아-태평양) 기준**이라 WHO 국제 기준과 다르다 — WHO는 25 과체중·30 비만이지만
한국은 23 비만 전단계·25 1단계 비만이다. 국내 사용자를 대상으로 하므로 대한비만학회 기준을 쓴다.
"""

from __future__ import annotations

# ── BMI 분류 (대한비만학회 2022) ─────────────────────────────────────────────
# 경계값은 "이 값 미만"의 상한이다. 18.5 미만 저체중, 18.5~22.9 정상, 23~24.9 비만 전단계, ...
BMI_NORMAL_MIN = 18.5
BMI_PRE_OBESE_MIN = 23.0
BMI_OBESE_1_MIN = 25.0
BMI_OBESE_2_MIN = 30.0
BMI_OBESE_3_MIN = 35.0

BMI_CATEGORY_LABELS: dict[str, str] = {
    "underweight": "저체중",
    "normal": "정상",
    "pre_obese": "비만 전단계",
    "obese_1": "1단계 비만",
    "obese_2": "2단계 비만",
    "obese_3": "3단계 비만",
}

# BMI 는 근육량을 구분하지 못한다 — 이 한계를 반드시 함께 알린다. 앱은 이 문구를 그대로 쓴다.
BMI_NOTICE = (
    "BMI는 대한비만학회 기준(한국인)이며 근육량과 체지방을 구분하지 못해요. "
    "운동량이 많거나 나이가 많으면 실제 체성분과 다를 수 있으니 참고 지표로만 봐주세요."
)

# ── 권장 신체활동량 (보건복지부 2023 · 질병관리청) ───────────────────────────
# 노인은 성인과 **고강도 상한이 다르고**(150 → 100분) 평형성 운동 축이 추가된다.
SENIOR_AGE_MIN = 65

AEROBIC_MODERATE_MIN_MINUTES = 150
AEROBIC_MODERATE_MAX_MINUTES = 300
AEROBIC_VIGOROUS_MIN_MINUTES = 75
ADULT_AEROBIC_VIGOROUS_MAX_MINUTES = 150
SENIOR_AEROBIC_VIGOROUS_MAX_MINUTES = 100

STRENGTH_DAYS_MIN = 2
SENIOR_BALANCE_DAYS_MIN = 3

SEDENTARY_TIP = "하루 중 앉아 있는 시간을 가능한 한 줄이세요."
INTENSITY_TIP = "고강도 1분은 중강도 2분에 해당해요."
STRENGTH_TIP = "근력운동은 8~12회 반복으로 신체 각 부위를 고르게 하세요."
BALANCE_TIP = "평형성 운동을 함께 하면 낙상 예방에 도움이 돼요."

ACTIVITY_SOURCE_LABEL = "보건복지부 「한국인을 위한 신체활동 지침서」(2023)"

# 활동 권고를 노출할 때 함께 내려보내는 고지 (docs/ACTIVITY_GUIDANCE.md §4).
# 질병 유무로 문구를 나누지 **않는다** — 이 권고를 싣는 GET /api/me/profile 은 sensitive_health 동의
# 없이 접근하는 라우트라, 문구를 바꾸려고 질병을 읽으면 그 라우트의 동의 요건이 달라진다
# (estimate 에 등급을 싣지 않은 것과 같은 판단, CKD_NUTRITION.md 3-5). 그래서 모두에게 상담 안내를 준다.
ACTIVITY_NOTICE = (
    "건강한 성인 기준의 일반 권고예요. 의료기기가 아니며 질병을 진단·치료·예방하지 않습니다. "
    "질환이 있으면 운동 종류와 강도를 의료진과 상의해 정하세요."
)

# ── MET (대사당량) — 2단계(기기 연동)에서 활동 시간을 kcal 로 환산할 때 쓴다 ──
# 소비 kcal ≈ MET × 체중(kg) × 시간(h). 중강도 3.0~5.9, 고강도 6.0 이상.
MODERATE_MET_MIN = 3.0
VIGOROUS_MET_MIN = 6.0
ACTIVITY_METS: dict[str, float] = {
    "walking": 3.5,
    "brisk_walking": 4.3,
    "cycling": 6.8,
    "stairs": 8.0,
    "running_8kmh": 8.3,
}


def calculate_bmi(height_cm: float | None, weight_kg: float | None) -> float | None:
    """BMI = 체중(kg) ÷ 신장(m)². 소수 첫째 자리까지. 값이 없거나 0 이하면 None."""
    if height_cm is None or weight_kg is None:
        return None
    if height_cm <= 0 or weight_kg <= 0:
        return None

    height_m = height_cm / 100
    return round(weight_kg / (height_m * height_m), 1)


def bmi_category(bmi: float | None) -> str | None:
    """BMI → 대한비만학회 분류 코드. None 이면 None."""
    if bmi is None:
        return None
    if bmi < BMI_NORMAL_MIN:
        return "underweight"
    if bmi < BMI_PRE_OBESE_MIN:
        return "normal"
    if bmi < BMI_OBESE_1_MIN:
        return "pre_obese"
    if bmi < BMI_OBESE_2_MIN:
        return "obese_1"
    if bmi < BMI_OBESE_3_MIN:
        return "obese_2"
    return "obese_3"


def bmi_category_label(category: str | None) -> str | None:
    return BMI_CATEGORY_LABELS.get(category) if category is not None else None


def activity_guide(age: int | None) -> dict | None:
    """연령대별 주당 권장 활동량. 나이를 모르면 None.

    노인(65세 이상)은 고강도 상한이 낮고(150→100분) 평형성 운동이 추가된다.
    """
    if age is None or age < 0:
        return None

    is_senior = age >= SENIOR_AGE_MIN
    tips = [INTENSITY_TIP, STRENGTH_TIP, SEDENTARY_TIP]
    if is_senior:
        tips.append(BALANCE_TIP)

    return {
        "moderate_min_minutes": AEROBIC_MODERATE_MIN_MINUTES,
        "moderate_max_minutes": AEROBIC_MODERATE_MAX_MINUTES,
        "vigorous_min_minutes": AEROBIC_VIGOROUS_MIN_MINUTES,
        "vigorous_max_minutes": (
            SENIOR_AEROBIC_VIGOROUS_MAX_MINUTES
            if is_senior
            else ADULT_AEROBIC_VIGOROUS_MAX_MINUTES
        ),
        "strength_days": STRENGTH_DAYS_MIN,
        # 성인에게는 평형성 축이 없다 — 억지로 채우지 않고 None 으로 둔다.
        "balance_days": SENIOR_BALANCE_DAYS_MIN if is_senior else None,
        "is_senior": is_senior,
        "tips": tips,
        "source": ACTIVITY_SOURCE_LABEL,
        "notice": ACTIVITY_NOTICE,
    }
