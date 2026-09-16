"""민감정보 동의 개정 — 버전이 바뀌면 재동의 전까지 무효 (KCAL-22, 2026-09-13).

**이 테스트가 존재하는 이유**: 그전까지 `has_active_consent` 는 버전을 보지 않았다. 동의 문구를
넓혀 버전만 올리면 v1.0("혈액형·질병·알러지를 식단 추천에서 거르는 데만")에 동의한 사용자의
검사 수치·진료 메모를 **옛 동의로 계속 처리**하게 된다 — 개인정보보호법 제23조의 "알린 범위"를
벗어난다.

v1.0 행은 `create_consent` 로 만들 수 없다(옛 버전은 400). 개정 전에 쌓인 데이터를 흉내 내려고
행을 직접 넣는다.

403 문구는 앱과의 계약이라 서비스 상수를 import 하지 않고 **문자열 그대로** 박는다.
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from api.consent_api import router as consent_router
from api.dependencies import get_current_user
from api.lab_api import router as lab_router
from api.visit_api import router as visit_router
from database import get_db
from main import add_service_error_handlers
from models.consent_model import UserConsent
from models.health_model import CareVisit, LabResult
from services import consent_service, lab_service, visit_service
from timeutil import UTC, today_kst

LEGACY_VERSION = "v1.0"
CURRENT_VERSION = "v1.1"

OUTDATED_MESSAGE = "건강 정보 동의 내용이 바뀌었어요. 내 정보 → 동의 관리에서 다시 동의해 주세요."
REQUIRED_MESSAGE = "건강 민감정보 이용 동의가 필요합니다. 동의 후 다시 시도해주세요."

# 민감정보 동의가 걸린 라우트 중 대표 둘 — 질병(개정 전부터 받던 항목)과 검사 수치(v1.1 에서 알린 항목).
GATED_PATHS = ("/api/me/conditions", "/api/me/labs")


@pytest.fixture
def client(db, user):
    app = FastAPI()

    for router in (consent_router, lab_router, visit_router):
        app.include_router(router, prefix="/api")

    add_service_error_handlers(app)

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user

    with TestClient(app) as test_client:
        yield test_client


def _add_legacy_consent(
    db,
    user_id: int,
    kind: str = consent_service.SENSITIVE_HEALTH,
    version: str = LEGACY_VERSION,
    revoked: bool = False,
) -> UserConsent:
    """개정 전에 받은 동의. 한 달 전에 동의했다고 둔다 (재동의 행보다 앞서야 최신 판정이 맞다)."""
    agreed_at = datetime.now(UTC) - timedelta(days=30)
    row = UserConsent(
        user_id=user_id,
        kind=kind,
        version=version,
        agreed_at=agreed_at,
        revoked_at=agreed_at + timedelta(days=1) if revoked else None,
    )
    db.add(row)
    db.flush()
    return row


def _reconsent(client) -> dict:
    response = client.post(
        "/api/me/consents", json={"kind": "sensitive_health", "version": CURRENT_VERSION}
    )
    assert response.status_code == 201
    return response.json()


# ---- ① 낡은 동의는 403, 문구로 이유를 가른다 ----

def test_legacy_consent_is_forbidden_with_outdated_message(client, db, user):
    """v1.0 에만 동의한 사용자는 질병·검사 수치 라우트가 막히고, **바뀌었다**는 이유를 듣는다."""
    _add_legacy_consent(db, user.id)

    for path in GATED_PATHS:
        response = client.get(path)

        assert response.status_code == 403, path
        assert response.json()["detail"] == OUTDATED_MESSAGE


def test_no_consent_keeps_the_original_message(client):
    for path in GATED_PATHS:
        response = client.get(path)

        assert response.status_code == 403, path
        assert response.json()["detail"] == REQUIRED_MESSAGE


def test_revoked_legacy_consent_says_consent_required_not_changed(client, db, user):
    """철회한 사람에게 "내용이 바뀌었으니 다시 동의하라"고 하면 철회 의사를 무시하는 문구가 된다."""
    _add_legacy_consent(db, user.id, revoked=True)

    assert consent_service.get_consent_state(db, user.id) is consent_service.ConsentState.REVOKED

    for path in GATED_PATHS:
        response = client.get(path)

        assert response.status_code == 403, path
        assert response.json()["detail"] == REQUIRED_MESSAGE


# ---- ② 재동의하면 열린다 ----

def test_reconsent_with_current_version_opens_the_routes(client, db, user):
    _add_legacy_consent(db, user.id)

    body = _reconsent(client)

    assert body["version"] == CURRENT_VERSION
    assert body["is_current"] is True

    for path in GATED_PATHS:
        assert client.get(path).status_code == 200, path


def test_reconsent_with_legacy_version_is_still_rejected(client, db, user):
    """옛 문서를 띄운 앱의 재동의는 기록하지 않는다 (400 — 앱 업데이트 유도)."""
    _add_legacy_consent(db, user.id)

    response = client.post(
        "/api/me/consents", json={"kind": "sensitive_health", "version": LEGACY_VERSION}
    )

    assert response.status_code == 400
    assert client.get("/api/me/labs").status_code == 403


# ---- ③ 이력의 is_current ----

def test_consent_history_marks_which_rows_are_current(client, db, user):
    """옛 행은 이력으로 남고 false, 재동의 행은 true."""
    legacy = _add_legacy_consent(db, user.id)
    reconsented = _reconsent(client)

    response = client.get("/api/me/consents")

    assert response.status_code == 200
    by_id = {row["id"]: row for row in response.json()}
    assert by_id[legacy.id]["is_current"] is False
    assert by_id[legacy.id]["version"] == LEGACY_VERSION
    assert by_id[reconsented["id"]]["is_current"] is True
    # 최신 우선 정렬은 그대로다.
    assert response.json()[0]["id"] == reconsented["id"]


def test_is_current_is_true_for_kinds_without_a_known_version(client, db, user):
    """현재 버전을 모르는 kind 는 true — 동의 종류가 늘 때 서버만 먼저 배포돼도 깨지지 않게."""
    _add_legacy_consent(db, user.id, kind="future_kind", version="whatever")

    rows = client.get("/api/me/consents").json()

    assert [row["is_current"] for row in rows if row["kind"] == "future_kind"] == [True]
    assert consent_service.is_current_version("future_kind", "whatever") is True


# ---- ④ 낡은 동의도 철회되고 파기된다 ----

def test_outdated_consent_can_be_revoked_and_destroys_sensitive_data(client, db, user):
    """효력이 멈춘 동의라도 그 동의로 모은 데이터는 남아 있다 — 철회는 그것을 파기하는 유일한 경로다."""
    _add_legacy_consent(db, user.id)
    today = today_kst()
    scheduled = today + timedelta(days=14)
    lab_service.save_result(db, user.id, today, "potassium", Decimal("5.1"))
    visit_service.set_next_visit(db, user.id, scheduled, today=today, outcome="칼륨 조심하라고 하심")

    response = client.post("/api/me/consents/revoke", json={"kind": "sensitive_health"})

    assert response.status_code == 200
    assert consent_service.get_consent_state(db, user.id) is consent_service.ConsentState.REVOKED
    remaining_labs = db.scalar(
        select(func.count()).select_from(LabResult).where(LabResult.user_id == user.id)
    )
    assert remaining_labs == 0

    visit = db.scalar(select(CareVisit).where(CareVisit.user_id == user.id))
    assert visit.outcome is None
    assert visit.scheduled_on == scheduled


# ---- ⑤ 진료 메모는 낡은 동의에서 가려진다 ----

def test_visit_note_is_hidden_under_outdated_consent_and_returns_after_reconsent(client, db, user):
    _add_legacy_consent(db, user.id)
    today = today_kst()
    scheduled = today + timedelta(days=14)
    visit_service.set_next_visit(db, user.id, scheduled, today=today, outcome="칼륨 조심하라고 하심")

    body = client.get("/api/me/next-visit").json()

    # 날짜는 민감정보가 아니라 계속 보인다 — D-day 가 살아 있어야 한다.
    assert body["scheduled_on"] == scheduled.isoformat()
    assert body["outcome"] is None

    # 가리기만 하고 지우지 않는다.
    stored = db.scalar(select(CareVisit.outcome).where(CareVisit.user_id == user.id))
    assert stored == "칼륨 조심하라고 하심"

    _reconsent(client)

    assert client.get("/api/me/next-visit").json()["outcome"] == "칼륨 조심하라고 하심"


def test_writing_a_visit_note_under_outdated_consent_is_forbidden(client, db, user):
    """메모를 쓰는 것은 403(바뀌었다는 문구), 날짜만 고치는 것은 그대로 된다."""
    _add_legacy_consent(db, user.id)
    scheduled = (today_kst() + timedelta(days=10)).isoformat()

    with_note = client.put(
        "/api/me/next-visit", json={"scheduled_on": scheduled, "outcome": "인 조절하라고 하심"}
    )

    assert with_note.status_code == 403
    assert with_note.json()["detail"] == OUTDATED_MESSAGE

    date_only = client.put("/api/me/next-visit", json={"scheduled_on": scheduled})

    assert date_only.status_code == 200
    assert date_only.json()["scheduled_on"] == scheduled
    assert date_only.json()["outcome"] is None


# ---- ⑥ 범위가 넓어지지 않은 개정은 막지 않는다 (2026-09-16) ----
#
# 위 ①~⑤ 는 "범위가 넓어진 개정"(v1.0 → v1.1)의 동작이다. 그런데 2026-09-16 전에는 판정이
# "현재 버전이 아니면 무효" 하나뿐이라, 사실과 다른 문장을 바로잡는 정도의 개정에도 기존 동의자
# **전원**이 재동의 전까지 막혔다. 개인정보 보호법 제23조가 막는 것은 알린 범위를 벗어난
# 처리이지 문구 개정 자체가 아니다 — 그래서 재동의 대상 버전 집합으로 갈랐다.

def test_plain_wording_revision_does_not_block_existing_consenters(client, db, user, monkeypatch):
    """문구만 바뀐 개정(v1.1 → v1.2)에서 v1.1 동의자는 계속 쓸 수 있다."""
    _add_legacy_consent(db, user.id, version=CURRENT_VERSION)

    # 범위가 넓어지지 않은 개정: 현재 버전만 올리고 재동의 집합은 그대로 둔다.
    monkeypatch.setattr(consent_service, "SENSITIVE_HEALTH_VERSION", "v1.2")
    monkeypatch.setitem(
        consent_service._CURRENT_VERSIONS, consent_service.SENSITIVE_HEALTH, "v1.2"
    )

    assert consent_service.get_consent_state(db, user.id) is consent_service.ConsentState.ACTIVE

    for path in GATED_PATHS:
        assert client.get(path).status_code == 200, path

    # 막지는 않되 **바뀐 사실은 알린다** — 앱이 이 값으로 안내를 띄운다.
    row = next(
        item
        for item in client.get("/api/me/consents").json()
        if item["kind"] == consent_service.SENSITIVE_HEALTH
    )
    assert row["is_current"] is False


def test_scope_widening_revision_still_blocks(db, user, monkeypatch):
    """범위가 넓어진 개정은 옛 버전을 재동의 집합에 넣어 그대로 막는다."""
    _add_legacy_consent(db, user.id, version=CURRENT_VERSION)

    monkeypatch.setattr(consent_service, "SENSITIVE_HEALTH_VERSION", "v2.0")
    monkeypatch.setitem(
        consent_service._CURRENT_VERSIONS, consent_service.SENSITIVE_HEALTH, "v2.0"
    )
    monkeypatch.setattr(
        consent_service,
        "SENSITIVE_HEALTH_REVALIDATE_VERSIONS",
        frozenset({LEGACY_VERSION, CURRENT_VERSION}),
    )

    assert consent_service.get_consent_state(db, user.id) is consent_service.ConsentState.OUTDATED
