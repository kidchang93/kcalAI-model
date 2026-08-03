"""검사 수치의 규약 (`services/lab_service.py`, `docs/CARE_LOOP.md` §4).

지키는 것은 **해석하지 않는다**는 원칙과, 그 원칙이 코드로 새어 나가지 않게 하는 경계다.
정상/비정상 판정을 넣고 싶어지는 순간이 반드시 오는데(수치가 있으니까), 그건 진단이다.
"""

from datetime import date
from decimal import Decimal

import pytest

from models.auth_model import User
from services import lab_panels, lab_service

MEASURED = date(2026, 8, 1)


@pytest.fixture
def user(db):
    row = User(kakao_id="lab-test", nickname="검사테스터")
    db.add(row)
    db.flush()
    return row


def test_same_day_same_panel_overwrites(db, user):
    """결과지를 두 번 옮겨 적는 것은 실수지 새 검사가 아니다 — 덮어쓴다."""
    lab_service.save_result(db, user.id, MEASURED, "potassium", Decimal("5.1"))
    lab_service.save_result(db, user.id, MEASURED, "potassium", Decimal("4.8"))

    rows = lab_service.list_results(db, user.id, panel="potassium")

    assert len(rows) == 1
    assert float(rows[0].value) == 4.8


def test_unit_comes_from_the_server(db, user):
    """단위는 사용자가 고르지 않는다 — 섞이면 추이가 무의미해진다."""
    row = lab_service.save_result(db, user.id, MEASURED, "hba1c", Decimal("6.8"))

    assert row.unit == lab_panels.get_panel("hba1c").unit == "%"


def test_unknown_panel_is_rejected(db, user):
    with pytest.raises(lab_service.UnknownPanelError):
        lab_service.save_result(db, user.id, MEASURED, "없는항목", Decimal("1"))


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("-1"), Decimal("999")])
def test_absurd_values_are_rejected(db, user, value):
    """오타 방어다. **의학적 판정이 아니다** — 5.1 도 15 도 저장되고, 위험하다고 말하지 않는다."""
    with pytest.raises(lab_service.ValueOutOfRangeError):
        lab_service.save_result(db, user.id, MEASURED, "potassium", value)


def test_plausible_but_abnormal_value_is_saved(db, user):
    """비정상 수치를 막지 않는다 — 오히려 그런 값이야말로 남겨야 하는 근거다."""
    row = lab_service.save_result(db, user.id, MEASURED, "potassium", Decimal("6.4"))

    assert float(row.value) == 6.4


def test_delete_hides_other_users_rows(db, user):
    """남의 것과 없는 것을 구분하지 않는다 (다른 삭제 라우트와 같은 존재 은닉)."""
    other = User(kakao_id="lab-test-other", nickname="남")
    db.add(other)
    db.flush()

    row = lab_service.save_result(db, other.id, MEASURED, "egfr", Decimal("55"))

    assert lab_service.delete_result(db, user.id, row.id) is False
    assert lab_service.delete_result(db, user.id, 99999999) is False
    assert lab_service.delete_result(db, other.id, row.id) is True


def test_every_panel_has_a_source():
    """**출처 없는 수치를 쓰지 않는다.** 정상범위는 없을 수 있어도(혈압) 출처는 있어야 한다."""
    for panel in lab_panels.PANELS:
        assert panel.source.strip(), f"{panel.code}: 출처가 비어 있다"
        assert panel.unit.strip(), f"{panel.code}: 단위가 비어 있다"
        assert lab_panels.max_value(panel.code) > 0


def test_blood_pressure_has_no_reference_range():
    """혈압은 근거를 못 찾았으므로 범위를 비워 둔다 — 지어내지 않는다.

    KSN 자료는 고혈압 축을 다루지 않고, CHRONIC_NUTRITION_SOURCES.md 에도 목표 혈압
    수치는 정리돼 있지 않다(혈압 **감소 효과**만 있다). 근거가 생기면 그때 채운다.
    """
    for code in ("bp_systolic", "bp_diastolic"):
        assert lab_panels.get_panel(code).reference is None


def test_panels_used_by_guides_exist():
    """가이드가 다루는 질환의 검사 항목이 하나도 없으면 진료 리포트가 비어 보인다."""
    for condition in ("ckd", "diabetes", "hypertension"):
        assert any(condition in panel.conditions for panel in lab_panels.PANELS), (
            f"{condition}: 이 질환에 해당하는 검사 항목이 없다"
        )
