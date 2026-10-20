"""출처 링크 (`services/citations.py`, DATA_MODEL 34장).

2026-10-20 App Store 1.4.1 반려 — 근거 문장은 있었지만 **원문 링크가 없었다.** 여기서 지키는 것은
"화면에 나가는 근거 문장마다 링크가 붙는다"이다. 근거 문장에 새 문헌을 쓰고 목록에 넣는 것을
잊으면, 에러 없이 링크만 조용히 빠진다 — 이번 반려와 같은 상태로 되돌아간다.
"""

import pytest

from services import (
    chronic_food_rules,
    citations,
    ckd_food_rules,
    lab_panels,
    nutrition_guide,
)

# 문헌이 아니라 사용자 측정값이라 링크가 없는 것이 맞는 출처.
_USER_INPUT_SOURCES = {"사용자 입력(가정 혈압계·진료 측정값)"}


def _server_basis_texts() -> list[str]:
    """화면에 그대로 나가는 근거 문장 전부 — 가이드·검사·나트륨 기준선·참고치·고지문."""
    guide_sources = [
        source
        for code in nutrition_guide.available_conditions()
        for axis in nutrition_guide.get_guide(code).axes
        for source in axis.sources
    ]
    lab_sources = [p.source for p in lab_panels.PANELS if p.source not in _USER_INPUT_SOURCES]

    return [
        *guide_sources,
        *lab_sources,
        *ckd_food_rules.SODIUM_LIMIT_CITATIONS.values(),
        ckd_food_rules.SODIUM_LIMIT_CITATION_ANY_STAGE,
        *ckd_food_rules.REFERENCE_CITATIONS.values(),
        chronic_food_rules.HTN_SODIUM_CITATION,
        chronic_food_rules.DM_SODIUM_CITATION,
        ckd_food_rules.TIER_NOTICE,
        ckd_food_rules.POTASSIUM_PHOSPHORUS_REFERENCE_NOTICE,
        chronic_food_rules.SODIUM_TIER_NOTICE,
    ]


@pytest.mark.parametrize("text", _server_basis_texts())
def test_every_basis_text_has_a_link(text):
    """근거 문장마다 문헌 링크가 하나 이상 걸린다. 빠지면 그 문헌을 `CITATIONS` 에 넣는다."""
    assert citations.find(text), f"링크를 찾지 못한 근거 문장: {text}"


def test_multi_source_basis_links_every_document():
    """한 줄에 여러 문헌이 이어 붙은 기준선은 **전부** 링크가 걸린다 — 2권은 이름 없이 붙는다."""
    urls = [link["url"] for link in citations.find(ckd_food_rules.SODIUM_LIMIT_CITATION_ANY_STAGE)]
    codes = {c.code for c in citations.CITATIONS if c.url in urls}

    assert codes == {"ksn1", "ksn2", "kdigo2024"}


def test_links_follow_text_order_without_duplicates():
    links = citations.find("KDIGO 2024 · 대한신장학회 영양-식생활 관리 1권 p101", "KDIGO 2024")

    assert [link["publisher"] for link in links] == ["KDIGO", "대한신장학회"]


def test_registry_is_well_formed():
    codes = [c.code for c in citations.CITATIONS]
    urls = [c.url for c in citations.CITATIONS]

    assert len(set(codes)) == len(codes)
    assert len(set(urls)) == len(urls)
    # 앱은 https 만 연다. 한글 파일명은 인코딩해 둔다 — 공백·한글이 그대로면 열리지 않는 기기가 있다.
    assert all(url.startswith("https://") and url.isascii() and " " not in url for url in urls)


def test_condition_citations_cover_only_researched_conditions():
    links = citations.for_conditions(["ckd", "diabetes", "pregnancy"])

    assert [link["publisher"] for link in links] == ["대한신장학회", "대한신장학회", "대한당뇨병학회"]
    assert citations.for_conditions(["pregnancy", "cancer"]) == []


def test_merge_keeps_order_and_drops_duplicate_urls():
    first = citations.find("KDIGO 2024")
    second = citations.find("KDOQI 2020 · KDIGO 2024")

    assert [link["title"] for link in citations.merge(first, second)] == [
        first[0]["title"],
        citations.find("KDOQI 2020")[0]["title"],
    ]


@pytest.mark.parametrize("condition", nutrition_guide.available_conditions())
def test_guide_payload_links_every_axis(condition):
    payload = nutrition_guide.guide_payload(nutrition_guide.get_guide(condition))

    for axis in payload["axes"]:
        assert axis["citations"], f"{condition}/{axis['axis']}: 출처 링크가 없다"
