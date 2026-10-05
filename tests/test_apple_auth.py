"""Sign in with Apple 회귀 — DATA_MODEL.md 21장 'Sign in with Apple'.

**Apple 은 부르지 않는다.** 테스트용 RSA 키로 identity token 을 서명하고 JWKS 조회
(`PyJWKClient.fetch_data`)만 그 공개키로 바꾼다 — kid 매칭·서명·클레임 검증은 실제 코드가 돈다.
authorization code 교환은 `apple_client.exchange_code` 를 대체하고, 어댑터 자체는 `requests.post`
를 대체해 따로 검증한다.
"""

import base64
import io
import json
import logging
import time

import jwt
import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from api.auth_api import router
from crypto import decrypt
from database import get_db
from factories import make_user
from main import add_service_error_handlers
from models.auth_model import User
from models.consent_model import UserConsent
from models.subscription_model import UserSubscription
from services import account_service, apple_client
from services.errors import BadRequestError

KID = "test-apple-kid"
SUB = "000999.apple-test-sub.0001"
GOOD_CODE = "good-authorization-code"
REFRESH_TOKEN = "r_LEAK_CANARY_refresh_token"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_JWK = {
    **jwt.algorithms.RSAAlgorithm.to_jwk(_KEY.public_key(), as_dict=True),
    "kid": KID,
    "use": "sig",
    "alg": "RS256",
}
_REAL_EXCHANGE = apple_client.exchange_code


@pytest.fixture
def jwks(monkeypatch):
    """요청마다 새 클라이언트 — 이전 테스트의 JWK Set 캐시가 섞이지 않게 한다."""
    client = jwt.PyJWKClient(apple_client.KEYS_URL)
    monkeypatch.setattr(client, "fetch_data", lambda: {"keys": [_PUBLIC_JWK]})
    monkeypatch.setattr(apple_client, "_jwks_client", client)
    return client


@pytest.fixture
def exchanged(monkeypatch):
    """교환을 대체하고 호출된 코드를 기록한다 — '교환 전에 막았다'를 확인하는 데 쓴다."""
    calls: list[str] = []

    def _fake_exchange(code: str) -> str:
        calls.append(code)

        if code != GOOD_CODE:
            raise BadRequestError(apple_client.TOKEN_INVALID_MESSAGE)

        return REFRESH_TOKEN

    monkeypatch.setattr(apple_client, "exchange_code", _fake_exchange)
    return calls


@pytest.fixture
def client(db, jwks, exchanged):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    add_service_error_handlers(app)
    app.dependency_overrides[get_db] = lambda: db

    with TestClient(app) as test_client:
        yield test_client


def _claims(**overrides) -> dict:
    now = int(time.time())
    claims = {
        "iss": apple_client.ISSUER,
        "aud": apple_client.APPLE_BUNDLE_ID,
        "sub": SUB,
        "iat": now,
        "exp": now + 600,
    }
    claims.update(overrides)
    return claims


def _token(key=_KEY, kid: str = KID, **overrides) -> str:
    return jwt.encode(_claims(**overrides), key, algorithm="RS256", headers={"kid": kid})


def _unsigned_token() -> str:
    # alg=none — 서명 없이 클레임만 맞춘 위조. kid 는 진짜라 공개키 조회까지는 통과한다.
    def _segment(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header = {"alg": "none", "typ": "JWT", "kid": KID}
    return f"{_segment(json.dumps(header).encode())}.{_segment(json.dumps(_claims()).encode())}."


def _signup(client, **overrides):
    body = {
        "identity_token": _token(),
        "authorization_code": GOOD_CODE,
        "nickname": "  홍길동 ",
        "agreed_terms": True,
        "agreed_privacy": True,
        **overrides,
    }
    return client.post("/api/auth/apple/signup", json=body)


def _login(client, token: str):
    return client.post("/api/auth/apple/login", json={"identity_token": token})


def _apple_user(db) -> User | None:
    return db.scalar(select(User).where(User.apple_sub == SUB))


# ---- 로그인 · 가입 ----

@pytest.fixture
def make_user_for_sub(db):
    return make_user(db, kakao_id=None, apple_sub=SUB, apple_refresh_token=REFRESH_TOKEN)


def test_login_unregistered_apple_account_is_404(client):
    response = _login(client, _token())

    assert response.status_code == 404
    assert response.json() == {
        "detail": "가입되지 않은 Apple 계정입니다. 회원가입을 먼저 진행해주세요."
    }


def test_signup_creates_member_then_login_returns_same_user(client, db):
    response = _signup(client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["nickname"] == "홍길동"

    user = _apple_user(db)
    assert user.id == body["user"]["id"]
    assert user.kakao_id is None
    # refresh token 은 암호문으로 저장된다 — 평문이 DB 에 남지 않는다.
    stored = db.execute(
        text("SELECT apple_refresh_token FROM users WHERE id = :id"), {"id": user.id}
    ).scalar_one()
    assert stored != REFRESH_TOKEN
    assert decrypt(stored) == REFRESH_TOKEN
    # 회원·동의·구독이 함께 생긴다 (한 트랜잭션).
    kinds = set(db.scalars(select(UserConsent.kind).where(UserConsent.user_id == user.id)))
    assert kinds == {"terms", "privacy"}
    plan = db.scalar(select(UserSubscription.plan_code).where(UserSubscription.user_id == user.id))
    assert plan == "lite"

    login = _login(client, _token())

    assert login.status_code == 200
    assert login.json()["user"]["id"] == user.id
    assert login.json()["access_token"] != body["access_token"]


def test_signup_blank_nickname_is_stored_as_null(client, db):
    assert _signup(client, nickname="   ").status_code == 200
    assert _apple_user(db).nickname is None


# 토큰 검증은 보안 경계다 — 어느 하나라도 통과하면 남의 계정으로 로그인된다.
@pytest.mark.parametrize(
    "make_token",
    [
        pytest.param(lambda: _token(iat=int(time.time()) - 700, exp=int(time.time()) - 1), id="expired"),
        pytest.param(lambda: _token(aud="com.other.app"), id="aud-mismatch"),
        pytest.param(lambda: _token(iss="https://evil.example.com"), id="iss-mismatch"),
        pytest.param(lambda: _token(key=_OTHER_KEY), id="forged-signature"),
        pytest.param(_unsigned_token, id="alg-none"),
        pytest.param(lambda: _token(kid="unknown-kid"), id="unknown-kid"),
        pytest.param(lambda: "not-a-jwt", id="garbage"),
    ],
)
def test_invalid_identity_token_is_400(client, db, make_user_for_sub, make_token):
    # 가입된 회원이 있어도 토큰이 틀리면 들어가지 못한다 (404 가 아니라 400).
    response = _login(client, make_token())

    assert response.status_code == 400
    assert response.json() == {"detail": apple_client.TOKEN_INVALID_MESSAGE}


def test_valid_token_logs_in_registered_member(client, make_user_for_sub):
    # 위 파라미터 테스트의 대조군 — 같은 회원, 올바른 토큰이면 200 이다.
    assert _login(client, _token()).status_code == 200


def test_jwks_unreachable_is_503(client, jwks, monkeypatch):
    # 실제 urllib 연결 실패를 만든다 (닫힌 로컬 포트) — 가짜 예외로는 예외 매핑을 검증할 수 없다.
    monkeypatch.delattr(jwks, "fetch_data")
    monkeypatch.setattr(jwks, "uri", "https://127.0.0.1:9/auth/keys")

    response = _login(client, _token())

    assert response.status_code == 503
    assert response.json() == {"detail": apple_client.UNAVAILABLE_MESSAGE}


def test_signup_requires_both_agreements_before_using_code(client, db, exchanged):
    response = _signup(client, agreed_privacy=False)

    assert response.status_code == 400
    assert response.json() == {
        "detail": "서비스 이용약관과 개인정보 처리방침에 모두 동의해야 가입할 수 있습니다."
    }
    assert exchanged == []
    assert _apple_user(db) is None


def test_signup_rejects_stale_terms_version_before_using_code(client, exchanged):
    assert _signup(client, terms_version="0.1").status_code == 400
    assert exchanged == []


def test_signup_with_invalid_token_is_400_before_using_code(client, exchanged):
    response = _signup(client, identity_token=_token(key=_OTHER_KEY))

    assert response.status_code == 400
    assert exchanged == []


def test_signup_duplicate_is_400_without_exchanging_again(client, exchanged):
    assert _signup(client).status_code == 200

    response = _signup(client)

    assert response.status_code == 400
    assert response.json() == {"detail": "이미 가입된 Apple 계정입니다. 로그인으로 진행해주세요."}
    assert exchanged == [GOOD_CODE]


def test_signup_code_exchange_failure_is_400_and_creates_no_member(client, db):
    response = _signup(client, authorization_code="expired-code")

    assert response.status_code == 400
    assert response.json() == {"detail": apple_client.TOKEN_INVALID_MESSAGE}
    assert _apple_user(db) is None


def test_signup_without_siwa_config_is_503(client, db, monkeypatch):
    # 설정 없이 가입을 받으면 탈퇴 때 폐기할 토큰이 없다 — 그래서 막는다.
    monkeypatch.setattr(apple_client, "exchange_code", _REAL_EXCHANGE)
    monkeypatch.setattr(apple_client, "APPLE_TEAM_ID", "")

    response = _signup(client)

    assert response.status_code == 503
    assert response.json() == {"detail": apple_client.NOT_CONFIGURED_MESSAGE}
    assert _apple_user(db) is None


@pytest.mark.parametrize(
    "path, body",
    [
        ("login", {"identity_token": ""}),
        ("login", {"identity_token": "x" * 4097}),
        ("signup", {"authorization_code": ""}),
        ("signup", {"authorization_code": "x" * 513}),
        ("signup", {"nickname": "가" * 51}),
        ("signup", {"agreed_terms": None}),
    ],
)
def test_request_limits_are_422(client, path, body):
    base = {
        "identity_token": "x",
        "authorization_code": GOOD_CODE,
        "agreed_terms": True,
        "agreed_privacy": True,
    }
    payload = {**base, **body}
    payload = {key: value for key, value in payload.items() if value is not None}

    assert client.post(f"/api/auth/apple/{path}", json=payload).status_code == 422


# ---- 탈퇴 — Apple 토큰 폐기는 의무다 ----

def test_delete_account_revokes_apple_refresh_token(db, monkeypatch):
    revoked: list[str] = []
    monkeypatch.setattr(account_service, "revoke_token", revoked.append)
    monkeypatch.setattr(account_service, "unlink", lambda kakao_id: None)
    user = make_user(db, kakao_id=None, apple_sub=SUB, apple_refresh_token=REFRESH_TOKEN)
    # 커밋으로 속성을 만료시켜 deferred 컬럼이 실제로 DB 에서 읽히는 경로를 탄다.
    db.commit()

    account_service.delete_account(db, user)

    assert revoked == [REFRESH_TOKEN]
    assert _apple_user(db) is None


# ---- 어댑터 — client secret · 교환 · 폐기 ----

_EC_KEY = ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def siwa_config(monkeypatch):
    pem = _EC_KEY.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,  # .p8 과 같은 형식
        serialization.NoEncryption(),
    )
    monkeypatch.setattr(apple_client, "APPLE_TEAM_ID", "TEAM123456")
    monkeypatch.setattr(apple_client, "APPLE_SIWA_KEY_ID", "KEY1234567")
    monkeypatch.setattr(apple_client, "APPLE_SIWA_PRIVATE_KEY_B64", base64.b64encode(pem).decode())


@pytest.fixture
def error_log():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.ERROR)
    apple_client.logger.addHandler(handler)

    try:
        yield stream
    finally:
        apple_client.logger.removeHandler(handler)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _capture_post(monkeypatch, response: _FakeResponse) -> list[dict]:
    calls: list[dict] = []

    def _post(url, data, timeout):
        calls.append({"url": url, "data": data, "timeout": timeout})
        return response

    monkeypatch.setattr(requests, "post", _post)
    return calls


def test_client_secret_is_es256_signed_for_apple(siwa_config):
    secret = apple_client._client_secret()

    assert jwt.get_unverified_header(secret) == {"alg": "ES256", "kid": "KEY1234567", "typ": "JWT"}
    claims = jwt.decode(
        secret, _EC_KEY.public_key(), algorithms=["ES256"], audience="https://appleid.apple.com"
    )
    assert claims["iss"] == "TEAM123456"
    assert claims["sub"] == apple_client.APPLE_BUNDLE_ID
    # Apple 상한은 6개월(15,777,000초)이다.
    assert 0 < claims["exp"] - claims["iat"] <= 15_777_000


def test_broken_private_key_is_503_not_500(siwa_config, monkeypatch):
    monkeypatch.setattr(apple_client, "APPLE_SIWA_PRIVATE_KEY_B64", "bm90LWEta2V5")

    with pytest.raises(apple_client.AppleUnavailableError):
        apple_client.exchange_code(GOOD_CODE)


def test_exchange_code_posts_form_and_returns_refresh_token(siwa_config, monkeypatch):
    calls = _capture_post(monkeypatch, _FakeResponse(200, {"refresh_token": REFRESH_TOKEN}))

    assert apple_client.exchange_code(GOOD_CODE) == REFRESH_TOKEN

    (call,) = calls
    assert call["url"] == "https://appleid.apple.com/auth/token"
    assert call["data"]["client_id"] == apple_client.APPLE_BUNDLE_ID
    assert call["data"]["grant_type"] == "authorization_code"
    assert call["data"]["code"] == GOOD_CODE
    assert jwt.get_unverified_header(call["data"]["client_secret"])["alg"] == "ES256"
    assert call["timeout"] == apple_client.APPLE_TIMEOUT_SECONDS


def test_exchange_code_rejections(siwa_config, monkeypatch):
    # 만료·재사용된 코드는 400 — 앱이 Apple 로그인을 다시 띄운다.
    _capture_post(monkeypatch, _FakeResponse(400, {"error": "invalid_grant"}))
    with pytest.raises(BadRequestError):
        apple_client.exchange_code(GOOD_CODE)

    # 우리 키가 틀렸으면 재시도해도 풀리지 않는다 — 503.
    _capture_post(monkeypatch, _FakeResponse(400, {"error": "invalid_client"}))
    with pytest.raises(apple_client.AppleUnavailableError):
        apple_client.exchange_code(GOOD_CODE)


def test_revoke_token_posts_refresh_token(siwa_config, monkeypatch):
    calls = _capture_post(monkeypatch, _FakeResponse(200, {}))

    apple_client.revoke_token(REFRESH_TOKEN)

    (call,) = calls
    assert call["url"] == "https://appleid.apple.com/auth/revoke"
    assert call["data"]["token"] == REFRESH_TOKEN
    assert call["data"]["token_type_hint"] == "refresh_token"
    assert call["data"]["client_id"] == apple_client.APPLE_BUNDLE_ID


def test_revoke_token_never_raises_and_never_logs_the_token(siwa_config, error_log, monkeypatch):
    # 실패가 탈퇴(개인정보 파기)를 막으면 안 된다. 예외 메시지에 무엇이 있든 로그로 옮기지 않는다.
    def _down(*args, **kwargs):
        raise requests.exceptions.ConnectionError(f"boom token={REFRESH_TOKEN}")

    monkeypatch.setattr(requests, "post", _down)
    apple_client.revoke_token(REFRESH_TOKEN)

    _capture_post(monkeypatch, _FakeResponse(400, {"error": "invalid_client"}))
    apple_client.revoke_token(REFRESH_TOKEN)

    monkeypatch.setattr(apple_client, "APPLE_SIWA_KEY_ID", "")
    apple_client.revoke_token(REFRESH_TOKEN)

    logged = error_log.getvalue()
    assert REFRESH_TOKEN not in logged
    assert "ConnectionError" in logged
    assert "invalid_client" in logged
    assert "skipped" in logged
