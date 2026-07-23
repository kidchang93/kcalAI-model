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
