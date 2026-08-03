"""질환별 식이 가이드의 **규칙**을 고정한다 (`services/nutrition_guide.py`).

내용의 의학적 타당성은 테스트가 판정할 수 없다 — 그건 `docs/CKD_NUTRITION.md`·
`docs/CHRONIC_NUTRITION_SOURCES.md` 가 인용한 학회 지침과 전문가 감수의 몫이다.
여기서 지키는 것은 **문서가 정한 노출 원칙**(`CHRONIC_NUTRITION_SOURCES.md` §6)이며,
전부 어겨도 에러가 나지 않고 조용히 잘못되는 종류다:

- 출처 없는 문장을 쓰지 않는다 → 축마다 `sources` 가 비어 있지 않은지
- 근거 없는 질환을 지어내지 않는다 → 가이드 질환이 실제 `condition_types` 안에 있는지
- 병존에서 방향이 엇갈리는 축은 그 사실을 밝힌다 → 칼륨에 `caution` 이 있는지
"""

import pytest
from sqlalchemy import text

from services import nutrition_guide

# 근거 문서를 갖춘 질환. 늘리려면 먼저 조사 문서가 있어야 한다.
EXPECTED_CONDITIONS = {"ckd", "hypertension", "diabetes"}


def test_only_researched_conditions_have_guides():
    """조사하지 않은 질환에는 가이드가 없다 — 빈 것이 지어낸 것보다 낫다."""
    assert set(nutrition_guide.available_conditions()) == EXPECTED_CONDITIONS

    for code in ("pregnancy", "cancer", "없는코드"):
        assert nutrition_guide.get_guide(code) is None


def test_guide_conditions_exist_in_condition_types(db):
    """가이드의 질환 코드가 `condition_types` 에 실제로 있어야 한다.

    오타나 코드 변경으로 어긋나면 앱은 진입점을 그려 놓고 404 를 받는다.
    """
    codes = {row[0] for row in db.execute(text("SELECT code FROM condition_types")).all()}

    missing = EXPECTED_CONDITIONS - codes

    assert not missing, f"condition_types 에 없는 질환의 가이드가 있다: {sorted(missing)}"


@pytest.mark.parametrize("condition", sorted(EXPECTED_CONDITIONS))
def test_every_axis_cites_a_source(condition):
    """**출처 없는 문장을 쓰지 않는다.** 하나라도 틀리면 전부를 의심하게 된다."""
    guide = nutrition_guide.get_guide(condition)
    assert guide is not None
    assert guide.axes, f"{condition}: 축이 하나도 없다"

    for axis in guide.axes:
        assert axis.sources, f"{condition}/{axis.axis}: 출처가 비어 있다"
        assert all(source.strip() for source in axis.sources)
        assert axis.summary.strip(), f"{condition}/{axis.axis}: 요약이 비어 있다"
        assert axis.sections, f"{condition}/{axis.axis}: 본문이 없다"

        for section in axis.sections:
            assert section.paragraphs, f"{condition}/{axis.axis}/{section.title}: 문단이 없다"


def test_potassium_axes_warn_about_the_conflict():
    """칼륨은 CKD 와 고혈압에서 **방향이 반대**다. 양쪽 다 그 사실을 밝혀야 한다.

    이 경고가 빠지면 병존 사용자가 서로 반대인 안내를 각각 읽고 어느 쪽이 맞는지 모른 채
    스스로 판단하게 된다 — 이 앱이 가장 피해야 하는 상황이다
    (`docs/CHRONIC_NUTRITION_SOURCES.md` §3-2·§6).
    """
    for condition in ("ckd", "hypertension"):
        guide = nutrition_guide.get_guide(condition)
        potassium = next(axis for axis in guide.axes if axis.axis == "potassium")

        assert potassium.caution, f"{condition}: 칼륨 축에 병존 경고가 없다"
        assert "의료진" in potassium.caution


def test_axis_codes_match_warning_nutrients():
    """가이드 축 코드가 경고 응답의 `nutrient` 값과 같아야 한다.

    경고 배너는 `/guides/{condition}?axis={nutrient}` 로 이 화면을 연다. 코드가 어긋나면
    링크는 열리는데 **엉뚱한 축이 펼쳐지거나 아무것도 안 펼쳐진다** — 에러가 나지 않아
    조용히 잘못되는 종류다. (`services/nutrition_service.py` 의 축 이름이 진실이다.)
    """
    warning_nutrients = {"sodium", "potassium", "phosphorus", "sugar"}

    for condition in sorted(EXPECTED_CONDITIONS):
        for axis in nutrition_guide.get_guide(condition).axes:
            # 경고가 다루지 않는 축(단백질·탄수화물)은 가이드에만 있어도 된다 — 목록 진입으로 본다.
            if axis.axis in ("protein", "carbs"):
                continue

            assert axis.axis in warning_nutrients, (
                f"{condition}/{axis.axis}: 경고의 nutrient 값과 다르다. "
                f"경고에서 이 축으로 연결할 수 없다."
            )


def test_every_axis_warning_condition_has_a_guide(db):
    """**영양 축 경고가 나가는 질환에는 반드시 가이드가 있어야 한다.**

    앱은 경고 줄에 `nutrient` 가 있으면 "왜 이 경고가 떴나요?"를 붙이고
    `/guides/{code}?axis={nutrient}` 로 보낸다. 축 경고는 나가는데 가이드가 없으면
    **링크를 눌러서 404를 보게 된다.**

    지금 둘이 일치하는 것은 우연이 아니다 — 영양 축으로 판정할 수 있는 질환이 곧
    근거 문서를 갖춘 질환이기 때문이다. 다만 `condition_types.dietary_tags` 에 축 태그를
    추가하는 것만으로 깨지므로(예: 임신에 `low_sodium` 을 붙이는 순간) 여기서 묶어 둔다.
    """
    from services import ckd_food_rules

    axis_tags = {tag for tag, _nutrient, _display in ckd_food_rules.WARNING_AXES}

    rows = db.execute(
        text("SELECT code, dietary_tags FROM condition_types WHERE is_active")
    ).all()

    warning_conditions = {
        code for code, tags in rows if axis_tags & set(tags)
    }

    missing = warning_conditions - set(nutrition_guide.available_conditions())

    assert not missing, (
        f"축 경고는 나가는데 가이드가 없는 질환: {sorted(missing)}. "
        "경고의 '왜?' 링크가 404가 된다 — 가이드를 쓰거나 축 태그를 빼야 한다."
    )


def test_notice_is_not_a_prescription():
    """공통 고지가 '의료진과 상의'를 담아야 한다 (Apple 1.4.1 · 노출 원칙)."""
    assert "의료진" in nutrition_guide.GUIDE_NOTICE
    assert "처방이 아닙니다" in nutrition_guide.GUIDE_NOTICE
