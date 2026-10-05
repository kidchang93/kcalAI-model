"""진료 일정의 규약 (`services/visit_service.py`, `docs/CARE_LOOP.md` §1·§4-3).

지키는 것은 두 가지다. **예정은 사용자당 하나**라는 것(캘린더가 아니라 "다음 한 바퀴가 언제
끝나는가"를 아는 값이다), 그리고 **없는 상태가 오류가 아니라는 것**이다.
"""

from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from api.dependencies import get_current_user
from api.visit_api import router as visit_router
from database import get_db
from factories import make_user
from main import add_service_error_handlers
from models.health_model import CareVisit
from services import consent_service, visit_service
from services.errors import BadRequestError
from timeutil import today_kst

TODAY = date(2026, 8, 19)

# 앱과의 계약이라 서비스 상수를 import 하지 않고 문자열 그대로 박는다.
REQUIRED_MESSAGE = "건강 민감정보 이용 동의가 필요합니다. 동의 후 다시 시도해주세요."


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


# ---- 물어볼 것 (`questions`, 2026-10-05) ----

def _visit_rows(db, user_id: int) -> int:
    return db.scalar(select(func.count()).select_from(CareVisit).where(CareVisit.user_id == user_id))


def test_questions_without_a_date_create_an_undated_visit(db, user):
    """진료일을 정하기 전에 물어볼 것부터 담는 사람이 있다 — 날짜 없는 예정 행을 만든다."""
    visit_service.set_next_visit(db, user.id, None, today=TODAY, questions="칼륨 약 계속 먹나요?")

    visit = visit_service.get_next_visit(db, user.id)

    assert visit is not None
    assert visit.scheduled_on is None
    assert visit.questions == "칼륨 약 계속 먹나요?"


def test_date_later_fills_the_same_undated_visit(db, user):
    """질문을 먼저 담고 날짜를 나중에 넣어도 예정은 하나다."""
    visit_service.set_next_visit(db, user.id, None, today=TODAY, questions="칼륨 약 계속 먹나요?")
    visit_service.set_next_visit(db, user.id, TODAY + timedelta(days=30), today=TODAY)

    visit = visit_service.get_next_visit(db, user.id)

    assert _visit_rows(db, user.id) == 1
    assert visit.scheduled_on == TODAY + timedelta(days=30)
    assert visit.questions == "칼륨 약 계속 먹나요?"


def test_questions_only_keeps_the_date_and_outcome(db, user):
    """질문만 고치는 요청이 날짜·메모를 날리면 안 된다."""
    scheduled = TODAY + timedelta(days=10)
    visit_service.set_next_visit(db, user.id, scheduled, today=TODAY, outcome="싱겁게")
    visit_service.set_next_visit(db, user.id, None, today=TODAY, questions="운동 해도 되나요?")

    visit = visit_service.get_next_visit(db, user.id)

    assert visit.scheduled_on == scheduled
    assert visit.outcome == "싱겁게"
    assert visit.questions == "운동 해도 되나요?"


def test_empty_questions_clear_them(db, user):
    visit_service.set_next_visit(db, user.id, TODAY + timedelta(days=10), today=TODAY, questions="오타")
    visit_service.set_next_visit(db, user.id, None, today=TODAY, questions=" \n ")

    assert visit_service.get_next_visit(db, user.id).questions is None


def test_nothing_to_save_is_rejected(db, user):
    with pytest.raises(BadRequestError):
        visit_service.set_next_visit(db, user.id, None, today=TODAY)


# ---- API: 동의 규칙은 outcome 과 같다 ----

@pytest.fixture
def client(db, user):
    app = FastAPI()
    app.include_router(visit_router, prefix="/api")
    add_service_error_handlers(app)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user

    with TestClient(app) as test_client:
        yield test_client


def _consent(db, user) -> None:
    consent_service.create_consent(
        db, user.id, consent_service.SENSITIVE_HEALTH, consent_service.SENSITIVE_HEALTH_VERSION
    )


def test_api_questions_only_put_then_get(client, db, user):
    _consent(db, user)

    put = client.put("/api/me/next-visit", json={"questions": "칼륨 약 계속 먹나요?\n운동 해도 되나요?"})

    assert put.status_code == 200
    assert put.json()["scheduled_on"] is None

    body = client.get("/api/me/next-visit").json()

    assert body["scheduled_on"] is None
    assert body["questions"] == "칼륨 약 계속 먹나요?\n운동 해도 되나요?"
    assert body["outcome"] is None


def test_api_date_only_put_keeps_questions(client, db, user):
    _consent(db, user)
    scheduled = (today_kst() + timedelta(days=14)).isoformat()
    client.put("/api/me/next-visit", json={"questions": "운동 해도 되나요?"})

    body = client.put("/api/me/next-visit", json={"scheduled_on": scheduled}).json()

    assert body["scheduled_on"] == scheduled
    assert body["questions"] == "운동 해도 되나요?"


def test_api_questions_need_consent_and_are_hidden_without_it(client, db, user):
    """비어 있지 않은 질문은 403, 동의가 없으면 GET 이 가린다(저장값은 그대로)."""
    response = client.put("/api/me/next-visit", json={"questions": "칼륨 약 계속 먹나요?"})

    assert response.status_code == 403
    assert response.json()["detail"] == REQUIRED_MESSAGE
    assert _visit_rows(db, user.id) == 0

    # 동의했을 때 담은 질문 — 동의가 사라지면 가려진다.
    visit_service.set_next_visit(
        db, user.id, today_kst(), today=today_kst(), outcome="싱겁게", questions="운동 해도 되나요?"
    )

    body = client.get("/api/me/next-visit").json()

    assert body["scheduled_on"] == today_kst().isoformat()
    assert body["outcome"] is None
    assert body["questions"] is None
    assert visit_service.get_next_visit(db, user.id).questions == "운동 해도 되나요?"


def test_api_clearing_questions_needs_no_consent(client, db, user):
    """지우는 것은 민감정보를 새로 받는 것이 아니다."""
    visit_service.set_next_visit(db, user.id, today_kst(), today=today_kst(), questions="오타")

    response = client.put("/api/me/next-visit", json={"questions": ""})

    assert response.status_code == 200
    assert visit_service.get_next_visit(db, user.id).questions is None


def test_api_empty_body_is_400(client):
    for body in ({}, {"scheduled_on": None}):
        response = client.put("/api/me/next-visit", json=body)

        assert response.status_code == 400, body
        assert response.json()["detail"] == "저장할 진료일이나 메모를 입력해주세요."
