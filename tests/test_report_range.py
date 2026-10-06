"""진료 리포트 기간 — 서버가 정한다 (DATA_MODEL.md 32-5).

지키는 것: 상한(무료 14 · 약관 1.4 이전 가입 30 · 플러스 365)을 넘는 요청은 **400 이 아니라 잘라서** 준다.
기본 기간은 플러스 = 지난 진료일부터, 무료 = 상한만큼. 구간 비교는 플러스 전용(402)이고 판정하지 않는다.
앱은 이 응답의 `range` 와 compare 모양을 그대로 읽는다 — 키 이름을 문자열로 박아 둔다.
"""

from datetime import date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import get_current_user
from api.health_api import router as health_router
from database import get_db
from factories import make_user
from main import add_service_error_handlers, handle_plan_limit
from services import health_service, medical_report_service, subscription_service, visit_service
from services.subscription_service import PlanLimitError
from timeutil import UTC

TODAY = date(2026, 12, 1)


def _member(db, kakao_id: str, joined: datetime):
    user = make_user(db, kakao_id)
    user.created_at = joined
    db.flush()
    return user


@pytest.fixture
def free_user(db):
    return _member(db, "report-free", datetime(2026, 11, 1, tzinfo=UTC))



@pytest.fixture
def plus_user(db):
    user = _member(db, "report-plus", datetime(2026, 11, 1, tzinfo=UTC))
    subscription = subscription_service.get_subscription(db, user.id)
    subscription.plan_code = "plus"
    subscription.provider = "appstore"
    subscription.current_period_end = datetime.now(UTC) + timedelta(days=30)
    db.flush()
    return user


def _visit(db, user, day: date) -> None:
    # 그날 예정 → 다음 날짜를 넣어 닫는다 (32-6 의 실제 흐름).
    visit_service.set_next_visit(db, user.id, day, today=day - timedelta(days=1))


def _report(db, user, start=None, end=None) -> dict:
    return medical_report_service.build_report(db, user.id, start, end, today=TODAY)


# ---- 상한과 자르기 ----

def test_free_member_gets_14_days_clamped_not_rejected(db, free_user):
    report = _report(db, free_user, TODAY - timedelta(days=59), TODAY)

    assert report["range"]["plan"] == "free"
    assert report["range"]["max_days"] == 14
    assert report["range"]["clamped"] is True
    assert report["start_date"] == (TODAY - timedelta(days=13)).isoformat()
    assert report["kcal"]["total_days"] == 14




def test_plus_member_gets_up_to_365_days(db, plus_user):
    report = _report(db, plus_user, TODAY - timedelta(days=499), TODAY)

    assert report["range"]["plan"] == "plus"
    assert report["range"]["max_days"] == 365
    assert report["range"]["clamped"] is True
    assert report["kcal"]["total_days"] == 365


def test_short_request_is_not_clamped(db, free_user):
    report = _report(db, free_user, TODAY - timedelta(days=6), TODAY)

    assert report["range"]["clamped"] is False
    assert report["kcal"]["total_days"] == 7


def test_expired_plus_reads_as_free_range(db, plus_user):
    subscription = subscription_service.get_subscription(db, plus_user.id)
    subscription.current_period_end = datetime.now(UTC) - timedelta(days=1)
    db.flush()

    assert _report(db, plus_user)["range"]["max_days"] == 14


# ---- 기본 기간 ----

def test_free_default_is_the_cap(db, free_user):
    report = _report(db, free_user)

    assert report["end_date"] == TODAY.isoformat()
    assert report["start_date"] == (TODAY - timedelta(days=13)).isoformat()
    assert report["range"]["default_start_date"] == TODAY - timedelta(days=13)
    assert report["range"]["clamped"] is False


def test_plus_default_starts_at_last_visit(db, plus_user):
    last = TODAY - timedelta(days=40)
    _visit(db, plus_user, last)

    report = _report(db, plus_user)

    assert report["range"]["last_visit_on"] == last
    assert report["start_date"] == last.isoformat()


def test_plus_default_without_visit_is_90_days(db, plus_user):
    report = _report(db, plus_user)

    assert report["range"]["last_visit_on"] is None
    assert report["kcal"]["total_days"] == 90


def test_plus_default_with_visit_older_than_a_year_is_90_days(db, plus_user):
    _visit(db, plus_user, TODAY - timedelta(days=400))

    assert _report(db, plus_user)["kcal"]["total_days"] == 90


def test_free_member_still_sees_last_visit(db, free_user):
    """무료 화면도 '지난 진료부터 남긴 날 수'를 그린다 — 기간은 상한 그대로."""
    _visit(db, free_user, TODAY - timedelta(days=40))

    report = _report(db, free_user)

    assert report["range"]["last_visit_on"] == TODAY - timedelta(days=40)
    assert report["kcal"]["total_days"] == 14


def test_reversed_range_is_still_400(db, plus_user):
    with pytest.raises(subscription_service.BadRequestError):
        _report(db, plus_user, TODAY, TODAY - timedelta(days=1))


def test_trends_route_keeps_its_92_day_cap(db, plus_user):
    """365일은 리포트 경로만이다 — /me/trends 는 그대로 92일."""
    with pytest.raises(subscription_service.BadRequestError):
        health_service.get_trends(db, plus_user.id, TODAY - timedelta(days=100), TODAY)


# ---- 구간 비교 (플러스 전용) ----

def test_compare_is_plus_only(db, free_user):
    with pytest.raises(PlanLimitError) as raised:
        medical_report_service.build_compare(db, free_user.id, today=TODAY)

    assert raised.value.resource == "report_compare"
    assert raised.value.plan_code == "lite"


def test_compare_with_one_visit_has_no_previous(db, plus_user):
    last = TODAY - timedelta(days=20)
    _visit(db, plus_user, last)

    result = medical_report_service.build_compare(db, plus_user.id, today=TODAY)

    assert result["previous"] is None
    assert result["current"]["start_date"] == last
    assert result["current"]["end_date"] == TODAY
    assert result["current"]["total_days"] == 21


def test_compare_splits_at_visits_and_averages_recorded_days(db, plus_user):
    previous, last = TODAY - timedelta(days=100), TODAY - timedelta(days=10)
    _visit(db, plus_user, previous)
    _visit(db, plus_user, last)
    visit_service.set_next_visit(db, plus_user.id, TODAY + timedelta(days=80), today=TODAY)
    health_service.create_meal(
        db, plus_user.id, "lunch", datetime.combine(last, datetime.min.time(), tzinfo=UTC), None,
        [{"food_label": "비교테스트밥", "serving_ratio": 1, "kcal": 600, "source": "manual"}],
    )

    result = medical_report_service.build_compare(db, plus_user.id, today=TODAY)

    assert result["previous"]["start_date"] == previous
    assert result["previous"]["end_date"] == last - timedelta(days=1)
    assert result["current"]["start_date"] == last
    assert result["current"]["recorded_days"] == 1
    assert result["current"]["kcal_daily_avg"] == 600
    assert result["previous"]["kcal_daily_avg"] is None
    # 질환이 없으면(또는 동의가 없으면) 축은 빈 목록이다 — null 이 아니다.
    assert result["current"]["nutrients"] == []


# ---- 라우트 — 앱이 읽는 모양 ----

@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(health_router, prefix="/api")
    add_service_error_handlers(app)
    app.add_exception_handler(PlanLimitError, handle_plan_limit)
    app.dependency_overrides[get_db] = lambda: db

    with TestClient(app) as test_client:
        yield test_client


def test_report_route_without_dates_returns_range(client, free_user):
    client.app.dependency_overrides[get_current_user] = lambda: free_user

    response = client.get("/api/me/report")

    assert response.status_code == 200
    assert set(response.json()["range"]) == {
        "plan", "max_days", "last_visit_on", "clamped", "default_start_date"
    }


def test_compare_route_is_402_for_free(client, free_user):
    client.app.dependency_overrides[get_current_user] = lambda: free_user

    response = client.get("/api/me/report/compare")

    assert response.status_code == 402
    assert response.json()["resource"] == "report_compare"
    assert response.json()["code"] == "plan_limit_exceeded"


def test_compare_route_shape_for_plus(client, plus_user):
    client.app.dependency_overrides[get_current_user] = lambda: plus_user

    body = client.get("/api/me/report/compare").json()

    assert body["previous"] is None
    assert set(body["current"]) == {
        "start_date", "end_date", "total_days", "recorded_days", "kcal_daily_avg", "nutrients"
    }
