"""진료 일정의 규약 (`services/visit_service.py`, `docs/CARE_LOOP.md` §1·§4-3).

지키는 것은 두 가지다. **예정은 사용자당 하나**라는 것(캘린더가 아니라 "다음 한 바퀴가 언제
끝나는가"를 아는 값이다), 그리고 **없는 상태가 오류가 아니라는 것**이다.
"""

from datetime import date, timedelta

import pytest

from factories import make_user
from services import visit_service

TODAY = date(2026, 8, 19)


def test_no_schedule_is_not_an_error(db, user):
    """등록하지 않은 상태는 정상이다 — 앱이 '없음'과 '실패'를 구분하려 애쓰게 두지 않는다."""
    assert visit_service.get_next_visit(db, user.id) is None


def test_setting_twice_overwrites(db, user):
    """예정은 하나다. 새로 넣으면 기존 예정을 바꾼다 (행이 늘지 않는다)."""
    visit_service.set_next_visit(db, user.id, TODAY + timedelta(days=30), today=TODAY)
    visit_service.set_next_visit(db, user.id, TODAY + timedelta(days=45), today=TODAY)

    visit = visit_service.get_next_visit(db, user.id)

    assert visit is not None
    assert visit.scheduled_on == TODAY + timedelta(days=45)

    rows = (
        db.query(visit_service.CareVisit).filter(visit_service.CareVisit.user_id == user.id).all()
    )
    assert len(rows) == 1


def test_past_visit_is_not_returned_as_next(db, user):
    """다녀온 진료(`visited_on`)는 '다음 진료'가 아니다."""
    visit = visit_service.set_next_visit(db, user.id, TODAY + timedelta(days=10), today=TODAY)
    visit.visited_on = TODAY
    db.commit()

    assert visit_service.get_next_visit(db, user.id) is None


def test_far_future_is_rejected(db, user):
    """'2062년'처럼 손이 미끄러진 값만 막는다 — 의학적 판정이 아니라 오타 방어다."""
    with pytest.raises(visit_service.ScheduleOutOfRangeError):
        visit_service.set_next_visit(db, user.id, TODAY + timedelta(days=365 * 6), today=TODAY)


def test_long_past_is_rejected(db, user):
    with pytest.raises(visit_service.ScheduleOutOfRangeError):
        visit_service.set_next_visit(db, user.id, TODAY - timedelta(days=400), today=TODAY)


def test_recent_past_is_allowed(db, user):
    """진료를 다녀오고 다음 일정을 아직 못 정한 사람의 날짜가 지나 있는 것은 정상이다."""
    visit = visit_service.set_next_visit(db, user.id, TODAY - timedelta(days=3), today=TODAY)

    assert visit.scheduled_on == TODAY - timedelta(days=3)


def test_clear_is_idempotent(db, user):
    """지울 것이 없어도 실패하지 않는다 — 삭제는 멱등해야 한다."""
    assert visit_service.clear_next_visit(db, user.id) is False

    visit_service.set_next_visit(db, user.id, TODAY + timedelta(days=7), today=TODAY)

    assert visit_service.clear_next_visit(db, user.id) is True
    assert visit_service.get_next_visit(db, user.id) is None


def test_schedules_are_per_user(db, user):
    """남의 예정이 내 '다음 진료'로 새지 않는다."""
    other = make_user(db, kakao_id="visit-other", nickname="다른사람")

    visit_service.set_next_visit(db, other.id, TODAY + timedelta(days=5), today=TODAY)

    assert visit_service.get_next_visit(db, user.id) is None


def test_outcome_is_kept_when_not_sent(db, user):
    """날짜만 고치는 요청이 메모를 날리면 안 된다 — None 은 '안 건드림'이다."""
    visit_service.set_next_visit(
        db, user.id, TODAY + timedelta(days=10), today=TODAY, outcome="칼륨 조심하라고 하심"
    )
    visit_service.set_next_visit(db, user.id, TODAY + timedelta(days=20), today=TODAY)

    visit = visit_service.get_next_visit(db, user.id)

    assert visit is not None
    assert visit.outcome == "칼륨 조심하라고 하심"
    assert visit.scheduled_on == TODAY + timedelta(days=20)


def test_empty_outcome_clears_it(db, user):
    """빈 문자열은 '지움'이다 — 지우는 방법이 없으면 잘못 적은 메모가 영원히 남는다."""
    visit_service.set_next_visit(db, user.id, TODAY + timedelta(days=10), today=TODAY, outcome="오타")
    visit_service.set_next_visit(db, user.id, TODAY + timedelta(days=10), today=TODAY, outcome="  ")

    visit = visit_service.get_next_visit(db, user.id)

    assert visit is not None
    assert visit.outcome is None
