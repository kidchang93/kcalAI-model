"""고혈압·당뇨 식이 규칙 — 근거는 `docs/CHRONIC_NUTRITION_SOURCES.md`.

신장병(CKD)은 `ckd_food_rules.py`가 대한신장학회 지침을 담당한다. 이 모듈은 대한고혈압학회
(KSH 2026 제6판)·대한당뇨병학회(KDA 2025 제9판) 지침을 담당하며, 등급 계산 유틸(`_tier_by_mg`·
`_stricter`)은 CKD 모듈의 것을 그대로 재사용한다 — 등급 체계가 갈리면 병존 판정이 깨진다.

**이 파일에 없는 것에는 이유가 있다.** 한 끼 탄수화물 임계값과 총당류 단독 경고는 지침 근거가
없어서 의도적으로 구현하지 않았다 (`CHRONIC_NUTRITION_SOURCES.md` §5). 나중에 "빠졌으니 채우자"고
추가하지 말 것 — 임상 감수가 선행되어야 한다.
"""

from services.ckd_food_rules import _matches, _stricter, _tier_by_mg

# ── 지침 수치 (§4-1) ────────────────────────────────────────────────────────
# 고혈압 나트륨 1일 상한. KSH2026 권고 21 (근거수준 I, A) — 2022년 6 g(2,400 mg)에서 하향됐다.
HTN_SODIUM_MG_PER_DAY = 2000
# 당뇨 나트륨 1일 상한. KDA2025 권고 9.
DM_SODIUM_MG_PER_DAY = 2300
# 당뇨병콩팥병. KSN-DKD 4.1.1 — 고혈압과 같은 값이라 병존해도 충돌하지 않는다.
DKD_SODIUM_MG_PER_DAY = 2000
# 이 아래로는 내리도록 유도하지 않는다. KDA2025 권고 9 본문(엄격한 제한의 근거 부족).
SODIUM_MG_PER_DAY_FLOOR = 1500

# ── 정책값 (§4-2) — 지침 컷오프가 아니다. 노출 시 반드시 고지문을 동반한다 ──────
# 2,000 ÷ 3끼 ≈ 667 을, 국내 유일한 법정 1회 제공량 기준(고열량·저영양 식사대용 나트륨
# 600 mg 초과)에 맞춰 내린 값이다.
SODIUM_SERVING_HIGH_MG = 600
SODIUM_SERVING_MID_MG = 300
# 면류 예외. 국물 면요리는 1인분 나트륨이 구조적으로 높아 일반 기준을 그대로 대면 거의 전부가
# high 로 걸린다 — 경고가 상시화되면 사용자는 경고 전체를 무시한다(CKD에서 국·장류를 다룬 방식).
SODIUM_SERVING_HIGH_MG_NOODLE = 1000

# 면류 판정용. 국물을 남기면 실제 섭취는 크게 줄어드는 군이다.
NOODLE_KEYWORDS: tuple[str, ...] = (
    "라면", "국수", "칼국수", "우동", "짬뽕", "쫄면", "냉면", "메밀국수", "소바",
    "수제비", "짜장면", "잔치국수", "비빔국수", "막국수", "쌀국수", "파스타", "스파게티",
)

SODIUM_REDUCTION_TIP = (
    "국물을 남기고 젓갈·장아찌·가공식품을 줄이면 나트륨을 크게 낮출 수 있어요."
)

# 등급을 노출할 때 항상 함께 내린다 (§6 노출 원칙). 1인분 경계가 지침 컷오프가 아니라는 사실을
# 숨기지 않는다 — "1일 상한 ÷ 끼니 수"를 지지하는 지침 문장은 확인되지 않았다 (§5-6).
SODIUM_TIER_NOTICE = (
    "나트륨 1일 상한은 고혈압 2,000 mg(소금 5 g)입니다. "
    "여기 표시되는 한 끼 기준(높음 600 mg)은 1일 상한을 끼니로 나눈 참고값이며 진료 기준이 아닙니다."
)

# 당뇨에 등급을 노출할 때의 한계 고지 (§2-4). 혈당 반응은 GI·식이섬유·조리법에 좌우되는데
# 우리 DB에는 그 축이 없다. 이 고지 없이 탄수화물·당류 수치만 보이면 과신을 부른다.
DIABETES_LIMIT_NOTICE = (
    "혈당 반응은 같은 탄수화물 양이라도 식이섬유·조리법·먹는 순서에 따라 달라집니다. "
    "표시되는 수치는 참고용이며 혈당지수(GI)는 반영되어 있지 않습니다."
)


# 나트륨 1인분 **등급**을 매길 수 있는 질환 코드 (condition_types.code).
# CKD 를 넣지 않는 것이 핵심이다 — 병기별로 상한이 갈려 단일 등급이 성립하지 않는다.
SODIUM_TIER_CONDITIONS: frozenset[str] = frozenset({"hypertension", "diabetes"})


# ── 첨가당 (§2-2, KDA2025 권고 6) ───────────────────────────────────────────
# 지침 대상은 **첨가당**이지 총당류가 아니다. 지침 본문이 "총당류의 급원인 생과일·흰우유·
# 채소류는 건강에 유익하다"고 못박고 있어, 우리 DB 의 `sugar_g`(총당류)로 경고를 만들면
# 지침과 **방향이 반대인** 오류가 된다. 그래서 발동은 **이름 축만** 쓴다.
#
# **등급(tier)을 매기지 않는 이유 — 2026-07-25 실측.** 1인분 당류에 경계를 대려면 그 "1인분"이
# 사람이 한 번에 먹는 양이어야 하는데, 정작 당뇨의 주 대상군에서 그게 무너져 있다:
#
#   빵 및 과자류  1인분 평균 554 g (최대 2,972 g) · 당류 50 g 초과가 14.0%
#   음료 및 차류  1인분 평균 507 g (최대 1,000 g) · 당류 50 g 초과가 29.2%
#   (식사류는 정상 — 밥·국·찌개·볶음의 당류 50 g 초과는 0~1%)
#
# 케이크 6호 한 판(당류 207 g)·1 L 음료가 그대로 "1인분"으로 들어 있다. 여기에 17 g 경계를
# 대면 간식·음료가 거의 전부 '높음'이 되고, 문장에는 사용자가 먹지도 않은 양이 근거로 붙는다.
# 경고가 상시화되면 사용자는 경고 전체를 무시한다 (CKD 에서 국·장류로 배운 것).
# 임포트의 1인분 기준을 고치기 전에는 **등급을 만들지 않는다.**
SUGAR_TIER_CONDITIONS: frozenset[str] = frozenset()

# 가당음료 — 권고 6의 주 급원이다. 농축과즙·과일주스도 지침이 첨가당으로 분류한다
# ("액체로 섭취하면 혈당을 크게 높인다", §2-2).
SWEET_DRINK_KEYWORDS: tuple[str, ...] = (
    "콜라", "사이다", "탄산음료", "에너지음료", "이온음료", "스포츠음료",
    "과일주스", "오렌지주스", "포도주스", "사과주스", "과즙", "넥타",
    "식혜", "미숫가루", "밀크셰이크", "쉐이크", "스무디", "프라페", "에이드",
    "버블티", "밀크티", "가당요구르트", "요구르트", "유산균음료",
)

# 첨가당이 제조 과정에서 들어가는 간식류.
#
# ⚠️ **앞 6개는 당뇨의 `condition_types.exclude_keywords` 원본이다.** 질병에 영양소 축이 붙는
# 순간 경고 판정은 exclude_keywords 경로를 더 이상 타지 않는다(`nutrition_service`의
# "exclude_keywords 는 이 축들에 흡수됨"). 여기에 옮겨 담지 않으면 그동안 동작하던 설탕·케이크
# 경고가 조용히 사라진다 — 축을 새로 열 때마다 확인해야 하는 지점이다.
ADDED_SUGAR_SNACK_KEYWORDS: tuple[str, ...] = (
    "설탕", "시럽", "꿀", "사탕", "초콜릿", "케이크",
    "도넛", "쿠키", "비스킷", "머핀", "마카롱", "젤리", "캬라멜", "카라멜",
    "아이스크림", "빙수", "슬러시", "파이", "타르트", "와플", "팬케이크",
    "약과", "양갱", "잼", "연유", "물엿", "조청",
)

# 위 키워드에 걸려도 **가당이 아닌 것**은 뺀다. 이름 축이 주(主)라 제외도 이름으로 한다.
#
# 뒤쪽 6개는 부분 문자열 매칭의 오탐이다 (`_matches`는 CKD 와 같은 방식으로 부분 일치를 쓴다).
# 2026-07-25에 식사·원물군 2,412행 전수로 확인한 것 — 채소(사탕수수·사탕무·콜라비·꿀풀)와
# 요리(비콜라장어·스**파이**시 리조또)가 간식 키워드에 걸렸다. 지침이 권장하는 채소를 경고하면
# 방향이 반대인 오류가 되므로 목록에 못박는다. 키워드를 추가할 때 같은 전수 검사를 다시 돌 것.
SUGAR_EXEMPT_KEYWORDS: tuple[str, ...] = (
    "무가당", "무설탕", "제로", "저당",
    "사탕수수", "사탕무", "콜라비", "콜라장어", "꿀풀", "스파이시",
)

ADDED_SUGAR_TIP = (
    "가당음료를 물·무가당 차로 바꾸는 것만으로도 첨가당을 크게 줄일 수 있어요. "
    "과일은 주스보다 그대로 드시는 편이 좋습니다."
)


# 실측 당류를 경고 문장에 **병기해도 되는 상한**. 이 값을 넘으면 그 행의 "1인분"은 사람이 한 번에
# 먹는 양이 아니라 제품 한 통·한 판이라고 본다(위 실측). 근거 수치가 오히려 사용자를 오도하므로
# 수치를 빼고 경고만 낸다. 정책값이다 — WHO 유리당 조건부 권고(25 g/일)의 2배를 경계로 잡았다.
SUGAR_SERVING_TRUSTWORTHY_MAX_G = 50.0


def trustworthy_sugar_g(sugar_g: float | None) -> float | None:
    """경고에 근거로 붙일 수 있는 1인분 당류만 통과시킨다. 아니면 None(수치 없이 경고만)."""
    if sugar_g is None or sugar_g > SUGAR_SERVING_TRUSTWORTHY_MAX_G:
        return None

    return sugar_g


def added_sugar_caution(label: str) -> str | None:
    """첨가당 급원인지 이름으로 판정한다. 걸린 키워드 또는 None.

    실측(`sugar_g`)을 쓰지 않는 것이 의도다 — 위 주석과 `CHRONIC_NUTRITION_SOURCES.md` §5-2.
    """
    if _matches(label, SUGAR_EXEMPT_KEYWORDS) is not None:
        return None

    return _matches(label, SWEET_DRINK_KEYWORDS) or _matches(label, ADDED_SUGAR_SNACK_KEYWORDS)


def is_noodle(label: str) -> bool:
    return _matches(label, NOODLE_KEYWORDS) is not None


def sodium_serving_high_mg(label: str) -> int:
    """이 음식에 적용할 1인분 '높음' 경계 (면류만 완화)."""
    return SODIUM_SERVING_HIGH_MG_NOODLE if is_noodle(label) else SODIUM_SERVING_HIGH_MG


def sodium_tier(label: str, sodium_mg: float | None) -> str | None:
    """1인분 실측 나트륨 등급. 미측정이면 None — 앱은 배지를 숨긴다.

    **CKD가 아니라 고혈압·당뇨에 쓴다.** CKD는 병기별로 상한이 갈려(비투석 2,000 · 투석 3,000)
    단일 등급을 매기지 않기로 했으나(`CKD_NUTRITION.md` 3-4), 고혈압은 병기 구분이 없어
    단일 기준이 성립한다.
    """
    return _tier_by_mg(sodium_mg, SODIUM_SERVING_MID_MG, sodium_serving_high_mg(label))


def sodium_display_tier(
    label: str,
    sodium_mg: float | None,
    name_tier: str | None = None,
) -> str | None:
    """이름 근거와 실측 등급 중 엄격한 쪽 (칼륨·인과 같은 이중 판정).

    실측 보유율이 96.9%로 높지만 어패류는 34.3%라(`PRODUCT_STRATEGY.md` §5-1) 젓갈·자반 같은
    고나트륨 원물이 실측 없이 새어 나간다. 이름 축을 함께 쓰는 이유다.
    """
    return _stricter(name_tier, sodium_tier(label, sodium_mg))
