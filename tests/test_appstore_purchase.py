"""App Store 인앱 구독 회귀 (DATA_MODEL.md 32-2~32-4).

지키는 명제: **앱이 보낸 transactionId 와 알림 본문은 조회 키일 뿐이다.** 상태·기간은 Apple 조회가 말하는
것만 쓰고, 남의 구독은 붙지 않으며(409), 우리가 Apple 구독을 청구하지 않는다(배치 provider 필터).

**Apple 은 호출하지 않는다** — 서비스 테스트는 `appstore_client` 의 조회 함수를, 어댑터 테스트는
`requests.get` 을 대체한다. 회원은 kakao_id 'appstore-*' 로 만든다.
"""

import base64
from datetime import datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.billing_api import router as billing_router
from api.dependencies import get_current_user
from database import get_db
from factories import make_user
from main import add_service_error_handlers
from models.auth_model import User
from models.subscription_model import UserSubscription
from services import account_service, appstore_client, billing_service, subscription_service
from services.appstore_client import AppStoreUnavailableError, SubscriptionStatus
from services.subscription_service import AppStoreConflictError
from timeutil import UTC

MONTHLY = "com.kcalai.kcalairn.plus.monthly"
CONFLICT_MESSAGE = "다른 계정에서 구독한 이용권이에요. 처음 구독한 계정으로 로그인해주세요."


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _jws(payload: dict) -> str:
    # 서버는 서명을 보지 않는다(32-3) — 아무 키로 서명해도 같은 페이로드로 읽혀야 한다.
    return jwt.encode(payload, "not-apple-only-shape-matters-32bytes", algorithm="HS256")


def _transaction(user_id: int, original: str, **overrides) -> dict:
    payload = {
        "transactionId": original,
        "originalTransactionId": original,
        "bundleId": appstore_client.APPLE_BUNDLE_ID,
        "productId": MONTHLY,
        "expiresDate": _ms(datetime.now(UTC) + timedelta(days=30)),
        "appAccountToken": subscription_service.app_account_token(user_id),
        "environment": "Production",
    }
    payload.update(overrides)
    return payload


class _AppleStub:
    """조회 대역. **몇 번 불렸는지**가 계약의 일부다 — 모르는 거래의 알림에는 부르면 안 된다."""

    def __init__(self) -> None:
        self.transactions: dict[str, tuple[dict, str]] = {}
        self.statuses: dict[str, SubscriptionStatus] = {}
        self.status_calls: list[tuple[str, str]] = []
        self.error: Exception | None = None

    def get_transaction(self, transaction_id: str):
        if self.error is not None:
            raise self.error
        return self.transactions.get(transaction_id)

    def get_subscription_status(self, original_id: str, environment: str):
        self.status_calls.append((original_id, environment))
        if self.error is not None:
            raise self.error
        return self.statuses.get(original_id)

    def sell(self, user_id: int, original: str, *, apple_status: int = 1, renewal: dict | None = None,
             environment: str = "Production", **overrides) -> None:
        transaction = _transaction(user_id, original, **overrides)
        self.transactions[original] = (transaction, environment)
        self.statuses[original] = SubscriptionStatus(
            status=apple_status, transaction=transaction, renewal=renewal or {"autoRenewStatus": 1}
        )


@pytest.fixture
def apple(monkeypatch) -> _AppleStub:
    stub = _AppleStub()
    monkeypatch.setattr(appstore_client, "get_transaction", stub.get_transaction)
    monkeypatch.setattr(appstore_client, "get_subscription_status", stub.get_subscription_status)
    return stub


def _subscription(db, user_id: int) -> UserSubscription:
    return db.scalar(select(UserSubscription).where(UserSubscription.user_id == user_id))


# ---- 1) 구매 확인 ----

def test_verify_grants_plus_without_billing_schedule(db, apple):
    user = make_user(db, "appstore-1")
    apple.sell(user.id, "2000000001")

    subscription_service.verify_appstore_purchase(db, user.id, "2000000001")

    subscription = _subscription(db, user.id)
    assert subscription.plan_code == "plus"
    assert subscription.provider == "appstore"
    assert subscription.status == "active"
    assert subscription.store_original_transaction_id == "2000000001"
    assert subscription.store_product_id == MONTHLY
    assert subscription.store_environment == "Production"
    # 우리가 청구하지 않는다 — 갱신은 Apple 이 한다.
    assert subscription.next_billing_at is None
    assert subscription.cancel_at_period_end is False
    assert subscription_service.get_user_plan(db, user.id).code == "plus"


def test_verify_marks_trial_and_auto_renew_off(db, apple):
    user = make_user(db, "appstore-2")
    apple.sell(user.id, "2000000002", offerType=1, offerDiscountType="FREE_TRIAL",
               renewal={"autoRenewStatus": 0})

    subscription_service.verify_appstore_purchase(db, user.id, "2000000002")

    subscription = _subscription(db, user.id)
    assert subscription.is_trial is True
    assert subscription.cancel_at_period_end is True
    # 해지 예약 — 기간까지는 플러스다.
    assert subscription.status == "canceled"
    assert subscription_service.get_user_plan(db, user.id).code == "plus"


@pytest.mark.parametrize(
    "overrides",
    [{"productId": "com.kcalai.kcalairn.other"}, {"bundleId": "com.example.other"}],
)
def test_verify_rejects_non_plus_or_other_bundle(db, apple, overrides):
    user = make_user(db, "appstore-3")
    apple.sell(user.id, "2000000003", **overrides)

    with pytest.raises(subscription_service.BadRequestError):
        subscription_service.verify_appstore_purchase(db, user.id, "2000000003")

    assert _subscription(db, user.id) is None or _subscription(db, user.id).plan_code == "lite"


def test_verify_unknown_transaction_is_400(db, apple):
    user = make_user(db, "appstore-4")

    with pytest.raises(subscription_service.BadRequestError):
        subscription_service.verify_appstore_purchase(db, user.id, "2000000004")


def test_verify_rejects_another_members_token(db, apple):
    """같은 Apple ID 로 다른 회원 계정에서 '구매 복원'을 눌러도 붙지 않는다."""
    buyer = make_user(db, "appstore-5")
    other = make_user(db, "appstore-6")
    apple.sell(buyer.id, "2000000005")

    with pytest.raises(AppStoreConflictError):
        subscription_service.verify_appstore_purchase(db, other.id, "2000000005")

    assert subscription_service.get_user_plan(db, other.id).code == "lite"


def test_verify_rejects_subscription_already_owned_by_another_member(db, apple):
    """토큰이 없는 구매(앱 밖에서 시작)도 먼저 확인한 회원의 것이다 — 두 번째 회원은 409."""
    first = make_user(db, "appstore-7")
    second = make_user(db, "appstore-8")
    apple.sell(first.id, "2000000007", appAccountToken=None)

    subscription_service.verify_appstore_purchase(db, first.id, "2000000007")

    with pytest.raises(AppStoreConflictError):
        subscription_service.verify_appstore_purchase(db, second.id, "2000000007")


def test_reverify_by_the_owner_is_idempotent(db, apple):
    user = make_user(db, "appstore-9")
    apple.sell(user.id, "2000000009")

    subscription_service.verify_appstore_purchase(db, user.id, "2000000009")
    subscription_service.verify_appstore_purchase(db, user.id, "2000000009")

    assert _subscription(db, user.id).store_original_transaction_id == "2000000009"


def test_refunded_subscription_ends_at_revocation(db, apple):
    user = make_user(db, "appstore-10")
    revoked = datetime.now(UTC) - timedelta(hours=1)
    apple.sell(user.id, "2000000010", apple_status=5, revocationDate=_ms(revoked))

    subscription_service.verify_appstore_purchase(db, user.id, "2000000010")

    subscription = _subscription(db, user.id)
    assert abs(subscription.current_period_end - revoked) < timedelta(seconds=1)
    # 행은 plus 그대로 두고 읽을 때 무료로 해석한다 (24장 규약).
    assert subscription.plan_code == "plus"
    assert subscription_service.get_user_plan(db, user.id).code == "lite"


def test_expired_subscription_reads_as_free(db, apple):
    user = make_user(db, "appstore-11")
    apple.sell(user.id, "2000000011", apple_status=2,
               expiresDate=_ms(datetime.now(UTC) - timedelta(days=1)))

    subscription_service.verify_appstore_purchase(db, user.id, "2000000011")

    assert subscription_service.get_user_plan(db, user.id).code == "lite"


def test_grace_period_extends_access(db, apple):
    user = make_user(db, "appstore-12")
    grace_end = datetime.now(UTC) + timedelta(days=6)
    apple.sell(user.id, "2000000012", apple_status=4,
               expiresDate=_ms(datetime.now(UTC) - timedelta(days=1)),
               renewal={"autoRenewStatus": 1, "gracePeriodExpiresDate": _ms(grace_end)})

    subscription_service.verify_appstore_purchase(db, user.id, "2000000012")

    subscription = _subscription(db, user.id)
    assert subscription.status == "past_due"
    assert subscription_service.get_user_plan(db, user.id).code == "plus"


def test_unknown_expiry_never_grants_unlimited_plus(db, apple):
    """만료 시각이 없는 응답이 무기한 플러스가 되면 안 된다 — 기간 NULL 유료는 만료되지 않는다."""
    user = make_user(db, "appstore-13")
    apple.sell(user.id, "2000000013", expiresDate=None)

    subscription_service.verify_appstore_purchase(db, user.id, "2000000013")

    assert _subscription(db, user.id).current_period_end is not None
    assert subscription_service.get_user_plan(db, user.id).code == "lite"


def test_app_account_token_is_a_stable_uuid_per_member():
    first = subscription_service.app_account_token(1)

    assert first == subscription_service.app_account_token(1)
    assert first != subscription_service.app_account_token(2)
    assert len(first) == 36 and first.count("-") == 4
    # user_id 를 그대로 담지 않는다 — 추측할 수 없어야 한다.
    assert "0000-0000" not in first


def test_my_subscription_view_carries_store_fields(db, apple):
    user = make_user(db, "appstore-14")
    apple.sell(user.id, "2000000014", offerType=1)
    subscription_service.verify_appstore_purchase(db, user.id, "2000000014")

    view = subscription_service.my_subscription_view(db, user.id)

    assert view["plan"]["code"] == "plus"
    assert view["provider"] == "appstore"
    assert view["store_product_id"] == MONTHLY
    assert view["is_trial"] is True
    assert view["app_account_token"] == subscription_service.app_account_token(user.id)


# ---- 2) 알림 — 본문을 믿지 않는다 ----

def _notification(original: str, **transaction) -> str:
    inner = _jws({"originalTransactionId": original, **transaction})
    return _jws({"notificationType": "REFUND", "data": {"signedTransactionInfo": inner}})


def test_notification_for_unknown_transaction_does_not_call_apple(db, apple):
    result = subscription_service.handle_appstore_notification(db, _notification("2999999999"))

    assert result == "unknown"
    assert apple.status_calls == []


@pytest.mark.parametrize("payload", [None, "", "garbage", _jws({"data": "x"}), _jws({"no": "data"})])
def test_malformed_notification_is_ignored_without_apple(db, apple, payload):
    assert subscription_service.handle_appstore_notification(db, payload) == "ignored"
    assert apple.status_calls == []


def test_notification_updates_only_from_requery(db, apple):
    """본문이 '환불됐다'고 해도 Apple 재조회가 활성이면 플러스 그대로다 (위조 본문 무력화)."""
    user = make_user(db, "appstore-15")
    apple.sell(user.id, "2000000015", environment="Sandbox")
    subscription_service.verify_appstore_purchase(db, user.id, "2000000015")

    forged = _notification("2000000015", revocationDate=_ms(datetime.now(UTC)), productId="x")
    result = subscription_service.handle_appstore_notification(db, forged)

    assert result == "updated"
    # 환경도 본문이 아니라 원장에서 — verify 때 Apple 이 답한 Sandbox 로 다시 묻는다.
    assert apple.status_calls[-1] == ("2000000015", "Sandbox")
    assert subscription_service.get_user_plan(db, user.id).code == "plus"


def test_notification_applies_refund_seen_by_requery(db, apple):
    user = make_user(db, "appstore-16")
    apple.sell(user.id, "2000000016")
    subscription_service.verify_appstore_purchase(db, user.id, "2000000016")
    apple.sell(user.id, "2000000016", apple_status=5,
               revocationDate=_ms(datetime.now(UTC) - timedelta(minutes=1)))

    subscription_service.handle_appstore_notification(db, _notification("2000000016"))

    assert subscription_service.get_user_plan(db, user.id).code == "lite"


# ---- 3) 갱신 배치는 App Store 구독을 청구하지 않는다 ----

def test_renew_batch_never_charges_appstore_subscription(db, apple, monkeypatch):
    """IAP 구독이 청구 대상에 섞이면 빌링키가 없어 멀쩡한 구독을 past_due 로 떨어뜨린다(30장)."""
    user = make_user(db, "appstore-17")
    apple.sell(user.id, "2000000017")
    subscription_service.verify_appstore_purchase(db, user.id, "2000000017")
    subscription = _subscription(db, user.id)
    # 데이터 이상으로 청구 예정이 붙어 있어도 provider 가 막는다.
    subscription.next_billing_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    charges = []
    monkeypatch.setattr(billing_service.toss_client, "charge_billing", lambda **kw: charges.append(kw))

    billing_service.charge_due_subscriptions(db)

    db.refresh(subscription)
    assert charges == []
    assert subscription.status == "active"


# ---- 4) 탈퇴는 새 컬럼과 함께 된다 ----

def test_delete_account_with_appstore_subscription(db, apple, monkeypatch):
    monkeypatch.setattr(account_service, "unlink", lambda kakao_id: None)
    monkeypatch.setattr(account_service, "revoke_token", lambda token: None)
    user = make_user(db, "appstore-18")
    apple.sell(user.id, "2000000018")
    subscription_service.verify_appstore_purchase(db, user.id, "2000000018")
    user_id = user.id

    account_service.delete_account(db, user)

    assert db.scalar(select(User).where(User.id == user_id)) is None
    # 알림이 와도 모르는 거래가 된다 — 조회 없이 버린다.
    assert subscription_service.handle_appstore_notification(db, _notification("2000000018")) == "unknown"


# ---- 5) 라우트 ----

@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(billing_router, prefix="/api")
    add_service_error_handlers(app)
    app.dependency_overrides[get_db] = lambda: db

    with TestClient(app) as test_client:
        yield test_client


def test_verify_route_maps_conflict_to_409(client, db, apple):
    buyer = make_user(db, "appstore-19")
    other = make_user(db, "appstore-20")
    apple.sell(buyer.id, "2000000019")
    client.app.dependency_overrides[get_current_user] = lambda: other

    response = client.post("/api/billing/appstore/verify", json={"transaction_id": "2000000019"})

    assert response.status_code == 409
    assert response.json() == {"detail": CONFLICT_MESSAGE}


def test_verify_route_returns_subscription(client, db, apple):
    user = make_user(db, "appstore-21")
    apple.sell(user.id, "2000000021")
    client.app.dependency_overrides[get_current_user] = lambda: user

    body = client.post("/api/billing/appstore/verify", json={"transaction_id": "2000000021"}).json()

    assert body["plan"]["code"] == "plus"
    assert body["provider"] == "appstore"
    assert body["next_billing_at"] is None


def test_verify_route_rejects_non_numeric_id(client, db, apple):
    """transactionId 는 Apple 조회 URL 경로에 실린다 — 숫자가 아니면 조회 전에 422."""
    user = make_user(db, "appstore-22")
    client.app.dependency_overrides[get_current_user] = lambda: user

    response = client.post("/api/billing/appstore/verify", json={"transaction_id": "1/../../x"})

    assert response.status_code == 422


def test_verify_route_maps_unavailable_to_503(client, db, apple):
    user = make_user(db, "appstore-23")
    apple.error = AppStoreUnavailableError(appstore_client.UNAVAILABLE_MESSAGE)
    client.app.dependency_overrides[get_current_user] = lambda: user

    response = client.post("/api/billing/appstore/verify", json={"transaction_id": "2000000023"})

    assert response.status_code == 503
    assert response.json() == {"detail": appstore_client.UNAVAILABLE_MESSAGE}


def test_notification_route_is_unauthenticated_and_hides_result(client, db, apple):
    user = make_user(db, "appstore-24")
    apple.sell(user.id, "2000000024")
    subscription_service.verify_appstore_purchase(db, user.id, "2000000024")

    known = client.post("/api/billing/appstore/notifications",
                        json={"signedPayload": _notification("2000000024")})
    unknown = client.post("/api/billing/appstore/notifications",
                          json={"signedPayload": _notification("2999999998")})
    junk = client.post("/api/billing/appstore/notifications", json={"hello": "world"})

    assert [r.status_code for r in (known, unknown, junk)] == [200, 200, 200]
    # 응답이 같아야 무인증 호출자가 거래의 존재를 떠볼 수 없다.
    assert known.json() == unknown.json() == junk.json() == {}


def test_notification_route_503_when_apple_requery_fails(client, db, apple):
    user = make_user(db, "appstore-25")
    apple.sell(user.id, "2000000025")
    subscription_service.verify_appstore_purchase(db, user.id, "2000000025")
    apple.error = AppStoreUnavailableError(appstore_client.UNAVAILABLE_MESSAGE)

    response = client.post("/api/billing/appstore/notifications",
                           json={"signedPayload": _notification("2000000025")})

    assert response.status_code == 503


# ---- 6) 어댑터 — 샌드박스 폴백 · 키 미유출 (requests 대체, Apple 미호출) ----

class _Response:
    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> dict:
        return self._body


@pytest.fixture
def iap_keys(monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    monkeypatch.setattr(appstore_client, "APPLE_IAP_KEY_ID", "KEYID12345")
    monkeypatch.setattr(appstore_client, "APPLE_IAP_ISSUER_ID", "issuer-uuid")
    monkeypatch.setattr(appstore_client, "APPLE_IAP_PRIVATE_KEY_B64", base64.b64encode(pem).decode())


def test_get_transaction_falls_back_to_sandbox(monkeypatch, iap_keys):
    """App Review 는 운영 서버에 샌드박스 구매로 들어온다 — 운영 4040010 이면 샌드박스를 본다."""
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        if url.startswith(appstore_client.BASE_URLS["Production"]):
            return _Response(404, {"errorCode": 4040010, "errorMessage": "Transaction id not found."})
        return _Response(200, {"signedTransactionInfo": _jws({"originalTransactionId": "77"})})

    monkeypatch.setattr(appstore_client.requests, "get", fake_get)

    transaction, environment = appstore_client.get_transaction("77")

    assert environment == "Sandbox"
    assert transaction["originalTransactionId"] == "77"
    assert len(calls) == 2


def test_get_transaction_not_found_anywhere_is_none(monkeypatch, iap_keys):
    monkeypatch.setattr(
        appstore_client.requests, "get",
        lambda url, headers, timeout: _Response(404, {"errorCode": 4040010}),
    )

    assert appstore_client.get_transaction("78") is None


def test_bearer_token_is_es256_for_appstoreconnect(monkeypatch, iap_keys):
    seen = {}

    def fake_get(url, headers, timeout):
        seen["token"] = headers["Authorization"].removeprefix("Bearer ")
        return _Response(404, {"errorCode": 4040001})

    monkeypatch.setattr(appstore_client.requests, "get", fake_get)
    appstore_client.get_transaction("79")

    header = jwt.get_unverified_header(seen["token"])
    claims = jwt.decode(seen["token"], options={"verify_signature": False})
    assert header["alg"] == "ES256" and header["kid"] == "KEYID12345"
    assert claims["aud"] == "appstoreconnect-v1"
    assert claims["bid"] == appstore_client.APPLE_BUNDLE_ID
    assert claims["iss"] == "issuer-uuid"


def test_network_failure_is_503_and_token_not_logged(monkeypatch, iap_keys, caplog):
    seen = {}

    def failing_get(url, headers, timeout):
        seen["token"] = headers["Authorization"]
        raise appstore_client.requests.ConnectionError(f"boom {headers['Authorization']}")

    monkeypatch.setattr(appstore_client.requests, "get", failing_get)

    with pytest.raises(AppStoreUnavailableError) as raised:
        appstore_client.get_transaction("80")

    assert raised.value.__cause__ is None
    assert seen["token"] not in caplog.text
    assert "ConnectionError" in caplog.text


def test_missing_keys_is_503_without_calling_apple(monkeypatch):
    monkeypatch.setattr(appstore_client, "APPLE_IAP_PRIVATE_KEY_B64", "")
    monkeypatch.setattr(
        appstore_client.requests, "get", lambda *a, **k: pytest.fail("Apple 을 부르면 안 된다")
    )

    with pytest.raises(AppStoreUnavailableError):
        appstore_client.get_transaction("81")
