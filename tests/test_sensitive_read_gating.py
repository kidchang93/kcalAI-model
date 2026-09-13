"""민감정보 읽기는 동의 상태를 따른다 — 라우트는 막지 않고 서비스가 거른다 (2026-09-13, DATA_MODEL 7장).

**이 테스트가 존재하는 이유**: 민감정보 동의를 v1.1 로 올리면서 낡은 동의(v1.0)를 무효로 만들었는데,
`/api/me/labs` 는 403 이 된 반면 **같은 칼륨 수치가 `/api/me/report` 에는 200 으로 실렸다**(실측).
summary·trends·report·guides 는 동의 없이 열리는 라우트라 "동의가 없으면 질병도 없다"(미동의는 입력
불가, 철회는 파기)에 기대고 있었는데, 낡은 동의는 **데이터를 가진 채 무효**라 그 전제가 깨졌다.

라우트를 403 으로 막지 않는 이유: 동의하지 않은 사용자도 칼로리 요약·끼니 리포트는 계속 써야 한다.
그래서 응답 형태는 그대로 두고, 질환·병기·검사 수치 자리만 "없음"으로 비운다.
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import get_current_user
from api.guide_api import router as guide_router
from api.health_api import router as health_router
from database import get_db
from models.auth_model import User
from models.consent_model import UserCondition, UserConsent, UserHealthProfile
from services import (
    consent_service,
    guide_service,
    health_service,
    lab_service,
    medical_report_service,
    nutrition_guide,
)
from timeutil import UTC

TODAY = datetime.now(UTC).date()
PERIOD_START = TODAY - timedelta(days=6)

# 앱·진료 문서에 그대로 나가는 문장이라 상수를 import 하지 않고 문자열로 박는다.
OUTDATED_SENTENCE = (
    "건강 정보 동의 내용이 바뀌어 다시 동의하기 전까지 질환·병기·검사 수치는 이 기록에 싣지 않았습니다."
)


@pytest.fixture
def user(db):
    row = User(kakao_id="read-gating-test", nickname="게이트테스터")
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def legacy_user(db, user):
    """개정 전(v1.0)에 동의하고 신장 질환·혈액투석·칼륨 검사를 입력해 둔 사용자."""
    db.add(
        UserConsent(
            user_id=user.id,
            kind=consent_service.SENSITIVE_HEALTH,
            version="v1.0",
            agreed_at=datetime.now(UTC) - timedelta(days=30),
        )
    )
    db.add(UserCondition(user_id=user.id, condition="ckd"))
    db.add(UserHealthProfile(user_id=user.id, ckd_stage="hemodialysis"))
    db.flush()
    lab_service.save_result(db, user.id, TODAY - timedelta(days=2), "potassium", Decimal("5.1"))
    return user


def _reconsent(db, user) -> None:
    consent_service.create_consent(
        db, user.id, consent_service.SENSITIVE_HEALTH, consent_service.SENSITIVE_HEALTH_VERSION
    )


def _report(db, user) -> dict:
    return medical_report_service.build_report(db, user.id, PERIOD_START, TODAY)


# ---- ① summary·trends ----

def test_outdated_consent_hides_disease_axes_from_summary_and_trends(db, legacy_user):
    assert health_service.get_summary(db, legacy_user.id, TODAY)["nutrients"] is None
    assert health_service.get_trends(db, legacy_user.id, PERIOD_START, TODAY)["nutrients"] is None


# ---- ② report ----

def test_outdated_consent_report_omits_sensitive_fields_and_says_why(db, legacy_user):
    """진료 문서에서 질환이 조용히 빠지면 "질환 없음"으로 읽힌다 — 빠진 이유를 문서에 남긴다."""
    report = _report(db, legacy_user)

    assert report["conditions"] == []
    assert report["ckd_stage_label"] is None
    assert report["labs"] == []
    assert report["nutrients"] is None
    assert report["notice"] == f"{medical_report_service.REPORT_NOTICE} {OUTDATED_SENTENCE}"


# ---- ③ guides ----

def test_outdated_consent_does_not_mark_my_guides(db, legacy_user):
    summaries = guide_service.list_guide_summaries(db, legacy_user.id)

    assert [summary["is_mine"] for summary in summaries] == [False] * len(summaries)
    # 내 질환을 앞으로 올리지 않았으니 기본 순서 그대로다.
    assert [summary["condition"] for summary in summaries] == list(nutrition_guide.available_conditions())


# ---- ④ 재동의하면 원래대로 ----

def test_reconsent_restores_summary_trends_report_and_guides(db, legacy_user):
    _reconsent(db, legacy_user)

    assert health_service.get_summary(db, legacy_user.id, TODAY)["nutrients"] is not None
    assert health_service.get_trends(db, legacy_user.id, PERIOD_START, TODAY)["nutrients"] is not None

    report = _report(db, legacy_user)
    assert "신장 질환" in report["conditions"]
    assert report["ckd_stage_label"] == "혈액투석"
    assert [lab["panel"] for lab in report["labs"]] == ["potassium"]
    assert report["nutrients"] is not None
    assert report["notice"] == medical_report_service.REPORT_NOTICE

    summaries = guide_service.list_guide_summaries(db, legacy_user.id)
    assert summaries[0]["condition"] == "ckd"
    assert summaries[0]["is_mine"] is True


# ---- ⑤ 동의 없음·철회에는 문장을 붙이지 않는다 ----

def test_missing_consent_report_has_no_outdated_sentence(db, user):
    """실을 데이터가 애초에 없다(입력 차단) — 빠진 것이 없는데 빠졌다고 쓰면 그것도 틀린 기록이다."""
    assert consent_service.get_consent_state(db, user.id) is consent_service.ConsentState.MISSING

    assert _report(db, user)["notice"] == medical_report_service.REPORT_NOTICE


def test_revoked_consent_report_has_no_outdated_sentence(db, user):
    """철회하면 파기된다 — 역시 실을 데이터가 없다."""
    _reconsent(db, user)
    consent_service.revoke_consent(db, user.id, consent_service.SENSITIVE_HEALTH)

    assert _report(db, user)["notice"] == medical_report_service.REPORT_NOTICE


# ---- 라우트는 막지 않는다 ----

@pytest.fixture
def client(db, legacy_user):
    app = FastAPI()
    app.include_router(health_router, prefix="/api")
    app.include_router(guide_router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: legacy_user

    with TestClient(app) as test_client:
        yield test_client


def test_routes_stay_open_and_blank_only_the_sensitive_fields(client):
    """동의가 낡아도 200 이다. 응답 형태는 그대로이고 민감정보 자리만 비어 있다."""
    summary = client.get(f"/api/me/summary?date={TODAY.isoformat()}")
    trends = client.get(f"/api/me/trends?start_date={PERIOD_START.isoformat()}&end_date={TODAY.isoformat()}")
    report = client.get(f"/api/me/report?start_date={PERIOD_START.isoformat()}&end_date={TODAY.isoformat()}")
    guides = client.get("/api/guides")

    assert [response.status_code for response in (summary, trends, report, guides)] == [200] * 4
    assert summary.json()["nutrients"] is None
    assert trends.json()["nutrients"] is None
    assert report.json()["conditions"] == []
    assert report.json()["labs"] == []
    assert report.json()["notice"].endswith(OUTDATED_SENTENCE)
    assert all(item["is_mine"] is False for item in guides.json()["conditions"])
