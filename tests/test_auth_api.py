"""카카오 로그인 라우트 회귀 (DATA_MODEL.md 21장).

카카오 서버는 부르지 않는다 — `api.auth_api` 가 import 한 `exchange_code`·`fetch_profile` 을
monkeypatch 로 대체해 콜백 이후 흐름만 검증한다.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth_api import router
from database import get_db


@pytest.fixture
def client(db, monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db

    import api.auth_api as auth_api

    # 카카오 왕복을 대체한다. 인가 코드 "good" → 회원번호 8100000001.
    def _fake_exchange(code: str) -> str:
        if code != "good":
            raise auth_api.KakaoAuthCodeError("카카오 로그인이 만료되었습니다. 다시 시도해주세요.")
        return "fake-access-token"

    monkeypatch.setattr(auth_api, "exchange_code", _fake_exchange)
    monkeypatch.setattr(auth_api, "fetch_profile", lambda _token: ("8100000001", "카카오유저"))

    # 리다이렉트는 따라가지 않는다 — Location 헤더 자체가 계약이다 (딥링크로 나간다).
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client


def _callback(client, state: str, code: str = "good"):
    return client.get(f"/api/auth/kakao/callback?code={code}&state={state}")


def _issue_state(platform: str = "native") -> str:
    from services.auth_service import create_state

    return create_state(platform)


def _link_code_from(response) -> str:
    from urllib.parse import parse_qs, urlparse

    return parse_qs(urlparse(response.headers["location"]).query)["code"][0]


# ---- start ----

def test_start_redirects_to_kakao(client):
    response = client.get("/api/auth/kakao/start")

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://kauth.kakao.com/oauth/authorize")
    # 일반(기본) 앱이 심사 없이 받을 수 있는 항목만 요청한다.
    assert "scope=profile_nickname" in location
    assert "state=" in location


def test_start_rejects_unknown_platform(client):
    assert client.get("/api/auth/kakao/start?platform=desktop").status_code == 422


# ---- callback ----

def test_callback_redirects_to_app_deeplink_with_link_code(client):
    response = _callback(client, _issue_state("native"))

    assert response.status_code == 302
    location = response.headers["location"]
    # 카카오는 커스텀 스킴을 Redirect URI 로 못 받으므로, 서버가 딥링크로 앱에 돌려준다.
    assert location.startswith("kcalairn://auth?")
    assert "is_new=true" in location
    assert "code=" in location


def test_callback_redirects_to_web_path_for_web_platform(client):
    response = _callback(client, _issue_state("web"))

    # 웹 빌드는 같은 오리진이라 딥링크가 아니라 경로로 돌려보낸다.
    assert response.headers["location"].startswith("/auth?")


def test_callback_rejects_forged_state(client):
    response = _callback(client, "forged.signature")

    # CSRF — 우리가 시작시키지 않은 콜백이다. 브라우저에 갇히지 않도록 에러도 딥링크로 보낸다.
    assert response.status_code == 302
    assert "error=invalid_state" in response.headers["location"]


def test_expired_web_state_returns_user_to_the_web_app(client):
    # state 가 깨져도 원래 왔던 곳으로 돌려보낸다. 웹 사용자를 딥링크(kcalairn://)로 보내면
    # 브라우저가 그 스킴을 열 수 없어 오류 화면에 갇힌다.
    from services.auth_service import create_state

    expired = create_state("web")
    forged = f"{expired.partition('.')[0]}.deadbeef"

    response = _callback(client, forged)

    assert response.headers["location"].startswith("/auth?")
    assert "error=invalid_state" in response.headers["location"]


def test_callback_passes_cancellation_back_to_app(client):
    response = client.get("/api/auth/kakao/callback?error=access_denied")

    assert "error=cancelled" in response.headers["location"]


def test_callback_reports_expired_authorization_code(client):
    response = _callback(client, _issue_state(), code="stale")

    assert "error=expired" in response.headers["location"]


# ---- signup · login ----

def test_signup_then_login_roundtrip(client):
    link_code = _link_code_from(_callback(client, _issue_state()))

    signup = client.post(
        "/api/auth/kakao/signup",
        json={"link_code": link_code, "agreed_terms": True, "agreed_privacy": True},
    )
    assert signup.status_code == 200
    body = signup.json()
    assert body["access_token"]
    assert body["user"]["nickname"] == "카카오유저"
    # 전화번호는 응답 계약에서 사라졌다.
    assert "phone_number" not in body["user"]

    # 두 번째 왕복은 기존 회원 → is_new=false, 로그인으로 처리된다.
    second = _callback(client, _issue_state())
    assert "is_new=false" in second.headers["location"]

    login = client.post(
        "/api/auth/kakao/login", json={"link_code": _link_code_from(second)}
    )
    assert login.status_code == 200
    assert login.json()["user"]["id"] == body["user"]["id"]


def test_login_with_unregistered_kakao_account_returns_404(client):
    link_code = _link_code_from(_callback(client, _issue_state()))

    response = client.post("/api/auth/kakao/login", json={"link_code": link_code})

    # 앱은 404를 받으면 가입 화면(동의·요금제)으로 보낸다.
    assert response.status_code == 404


def test_signup_requires_both_consents(client):
    link_code = _link_code_from(_callback(client, _issue_state()))

    response = client.post(
        "/api/auth/kakao/signup",
        json={"link_code": link_code, "agreed_terms": True, "agreed_privacy": False},
    )

    assert response.status_code == 400


def test_signup_rejects_missing_consent_fields(client):
    link_code = _link_code_from(_callback(client, _issue_state()))

    # 동의 필드에 기본값이 없다 — 앱이 빠뜨리면 422 로 막힌다.
    response = client.post("/api/auth/kakao/signup", json={"link_code": link_code})

    assert response.status_code == 422


def test_stale_link_code_is_rejected(client):
    link_code = _link_code_from(_callback(client, _issue_state()))
    client.post(
        "/api/auth/kakao/signup",
        json={"link_code": link_code, "agreed_terms": True, "agreed_privacy": True},
    )

    # 1회용이다.
    replay = client.post("/api/auth/kakao/login", json={"link_code": link_code})
    assert replay.status_code == 400


def test_switch_account_forces_the_kakao_login_screen(client):
    # 브라우저에 카카오 세션이 남아 있으면 카카오는 묻지 않고 같은 계정으로 인가한다.
    # prompt=login 이 있어야 계정을 바꿀 수 있다 (공용 PC 문제이기도 하다).
    default = client.get("/api/auth/kakao/start")
    switching = client.get("/api/auth/kakao/start?switch_account=true")

    assert "prompt=login" not in default.headers["location"]
    assert "prompt=login" in switching.headers["location"]
