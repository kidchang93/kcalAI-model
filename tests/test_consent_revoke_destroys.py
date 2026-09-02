"""동의 철회 = 민감정보 파기 (`services/consent_service._destroy_sensitive_data`).

**이 테스트가 존재하는 이유**: 2026-08-19까지 파기 목록이 혈액형·질병·알러지 셋에 멈춰 있었다.
리비전 0027(`lab_results`)·0028(`care_visits`)이 민감정보를 담는 테이블을 추가했는데 이 목록이
갱신되지 않아, 철회해도 검사 수치가 남아 있었다. 조회는 403으로 막혔지만 **파기는 접근을 막는
것이 아니라 없애는 것**이다.

같은 사고가 탈퇴 연쇄(`account_service`)에서도 두 번 있었다(2026-07-16 `payments`). 그래서
그쪽은 `tests/test_account_service.py`가 FK 전수를 대조한다. 여기는 그런 자동 대조가 불가능하다
— "민감정보인가"는 스키마가 아니라 판단이라서다. 대신 **판단의 결과를 못으로 박아 둔다.**
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from models.auth_model import User
from models.health_model import CareVisit, LabResult
from services import consent_service, lab_service, visit_service

TODAY = date(2026, 8, 19)


@pytest.fixture
def user(db):
    row = User(kakao_id="revoke-test", nickname="철회테스터")
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def consented(db, user):
    consent_service.create_consent(
        db,
        user.id,
        consent_service.SENSITIVE_HEALTH,
        consent_service.SENSITIVE_HEALTH_VERSION,
    )
    return user


def test_revoke_destroys_lab_results(db, consented):
    """검사 수치는 그 자체가 건강 민감정보다 — 철회하면 남지 않는다."""
    lab_service.save_result(db, consented.id, TODAY, "potassium", Decimal("5.1"))

    consent_service.revoke_consent(db, consented.id, consent_service.SENSITIVE_HEALTH)

    remaining = db.query(LabResult).filter(LabResult.user_id == consented.id).all()
    assert remaining == []


def test_revoke_clears_visit_note_but_keeps_the_date(db, consented):
    """진료 메모는 지우되 **날짜는 남긴다**.

    날짜는 민감정보가 아니라고 판단해 동의 없이도 쓰게 했다(31장). 철회했다고 진료 일정까지
    잃게 하는 것은 필요 이상의 파기다.
    """
    scheduled = TODAY + timedelta(days=14)
    visit_service.set_next_visit(
        db, consented.id, scheduled, today=TODAY, outcome="칼륨 조심하라고 하심"
    )

    consent_service.revoke_consent(db, consented.id, consent_service.SENSITIVE_HEALTH)

    visit = db.query(CareVisit).filter(CareVisit.user_id == consented.id).one()
    assert visit.outcome is None
    assert visit.scheduled_on == scheduled


def test_revoke_leaves_other_users_alone(db, consented):
    """남의 민감정보가 함께 파기되지 않는다."""
    other = User(kakao_id="revoke-other", nickname="다른사람")
    db.add(other)
    db.flush()
    consent_service.create_consent(
        db, other.id, consent_service.SENSITIVE_HEALTH, consent_service.SENSITIVE_HEALTH_VERSION
    )
    lab_service.save_result(db, other.id, TODAY, "hba1c", Decimal("6.8"))

    consent_service.revoke_consent(db, consented.id, consent_service.SENSITIVE_HEALTH)

    assert db.query(LabResult).filter(LabResult.user_id == other.id).count() == 1
