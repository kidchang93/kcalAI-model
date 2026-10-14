"""Google Play 구독 회귀 (DATA_MODEL.md 33-2~33-4).

지키는 명제: **앱이 보낸 purchaseToken 과 RTDN 본문은 조회 키일 뿐이다.** 상태·기간은 Google 조회가 말하는 것만
쓰고, 남의 구독은 붙지 않으며(409), acknowledge 는 서버가 하고, 우리가 Google 구독을 청구하지 않는다(배치 provider 필터).

**Google 은 호출하지 않는다** — 서비스 테스트는 `play_client` 의 조회·확인 함수를, 어댑터 테스트는 `requests` 를
대체한다. 회원은 kakao_id 'play-*' 로 만든다.
"""

import base64
import json
from datetime import datetime, timedelta

import jwt
import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.billing_api import router as billing_router
from api.dependencies import get_current_user
from database import get_db
from factories import make_user
from main import add_service_error_handlers
from models.subscription_model import UserSubscription
from services import billing_service, play_client, subscription_service
from services.play_client import PlayUnavailableError
from services.subscription_service import PlayConflictError
from timeutil import UTC

MONTHLY = "com.kcalai.kcalairn.plus.monthly"
YEARLY = "com.kcalai.kcalairn.plus.yearly"
CONFLICT_MESSAGE = "다른 계정에서 구독한 이용권이에요. 처음 구독한 계정으로 로그인해주세요."


def _rfc3339(moment: datetime) -> str:
    # Google 모양 — 밀리초 + Z.
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _purchase(user_id: int, *, state: str = "ACTIVE", product: str = MONTHLY, expiry: datetime | None = None,
              auto_renew: bool = True, acknowledged: bool = False, **overrides) -> dict:
    """SubscriptionPurchaseV2 모양. 자동 갱신이 꺼지면 autoRenewEnabled 가 **빠진다**(proto3 JSON 의 false 생략)."""
    purchase = {
        "kind": "androidpublisher#subscriptionPurchaseV2",
        "subscriptionState": f"SUBSCRIPTION_STATE_{state}",
        "acknowledgementState": (
            "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED" if acknowledged else "ACKNOWLEDGEMENT_STATE_PENDING"
        ),
        "lineItems": [
            {
                "productId": product,
                "expiryTime": _rfc3339(expiry or datetime.now(UTC) + timedelta(days=30)),
                "autoRenewingPlan": {"autoRenewEnabled": True} if auto_renew else {},
            }
        ],
        "externalAccountIdentifiers": {
            "obfuscatedExternalAccountId": subscription_service.app_account_token(user_id)
        },
    }
    purchase.update(overrides)
    return purchase


class _GoogleStub:
    """조회·확인 대역. **몇 번 불렸는지**가 계약의 일부다 — 모르는 토큰의 알림에는 부르면 안 된다."""

    def __init__(self) -> None:
        self.purchases: dict[str, dict] = {}
        self.get_calls: list[str] = []
        self.acks: list[tuple[str, str]] = []
        self.error: Exception | None = None

    def get_subscription(self, purchase_token: str):
        self.get_calls.append(purchase_token)
        if self.error is not None:
            raise self.error
        return self.purchases.get(purchase_token)

    def acknowledge(self, product_id: str, purchase_token: str) -> bool:
        self.acks.append((product_id, purchase_token))
        if self.error is not None:
            raise self.error
        return True

    def sell(self, user_id: int, purchase_token: str, **kwargs) -> None:
        self.purchases[purchase_token] = _purchase(user_id, **kwargs)


@pytest.fixture
def google(monkeypatch) -> _GoogleStub:
    stub = _GoogleStub()
    monkeypatch.setattr(play_client, "get_subscription", stub.get_subscription)
    monkeypatch.setattr(play_client, "acknowledge", stub.acknowledge)
    return stub


def _subscription(db, user_id: int) -> UserSubscription | None:
    return db.scalar(select(UserSubscription).where(UserSubscription.user_id == user_id))


def _verify(db, user_id: int, purchase_token: str, product_id: str = MONTHLY) -> UserSubscription:
    return subscription_service.verify_play_purchase(db, user_id, product_id, purchase_token)


# ---- 1) 구매 확인 ----

def test_verify_grants_plus_and_acknowledges(db, google):
    user = make_user(db, "play-1")
    google.sell(user.id, "playtoken-0001")

    _verify(db, user.id, "playtoken-0001")

    subscription = _subscription(db, user.id)
    assert subscription.plan_code == "plus"
    assert subscription.provider == "play"
    assert subscription.status == "active"
    assert subscription.store_purchase_token == "playtoken-0001"
    assert subscription.store_product_id == MONTHLY
    assert subscription.store_environment == "Production"
    # 우리가 청구하지 않는다 — 갱신은 Google 이 한다.
    assert subscription.next_billing_at is None
    assert subscription.cancel_at_period_end is False
    assert subscription_service.get_user_plan(db, user.id).code == "plus"
    # 3일 안에 확인하지 않으면 Google 이 환불한다 — 서버가 한다.
    assert google.acks == [(MONTHLY, "playtoken-0001")]


def test_verify_does_not_acknowledge_twice(db, google):
    user = make_user(db, "play-2")
    google.sell(user.id, "playtoken-0002", acknowledged=True)

    _verify(db, user.id, "playtoken-0002")

    assert google.acks == []


def test_auto_renew_off_is_canceled_but_plus_until_expiry_and_test_purchase_is_test(db, google):
    user = make_user(db, "play-3")
    google.sell(user.id, "playtoken-0003", auto_renew=False, testPurchase={})

    _verify(db, user.id, "playtoken-0003")

    subscription = _subscription(db, user.id)
    assert subscription.status == "canceled"
    assert subscription.cancel_at_period_end is True
    assert subscription.store_environment == "Test"
    assert subscription_service.get_user_plan(db, user.id).code == "plus"


def test_verify_rejects_non_plus_product_from_the_app_without_calling_google(db, google):
    user = make_user(db, "play-4")

    with pytest.raises(subscription_service.BadRequestError):
        _verify(db, user.id, "playtoken-0004", product_id="com.kcalai.kcalairn.other")

    assert google.get_calls == []


def test_verify_rejects_purchase_whose_line_items_are_not_plus(db, google):
    """앱이 플러스라고 말해도 Google 이 다른 상품이라고 하면 붙이지 않는다."""
    user = make_user(db, "play-5")
    google.sell(user.id, "playtoken-0005", product="com.kcalai.kcalairn.other")

    with pytest.raises(subscription_service.BadRequestError):
        _verify(db, user.id, "playtoken-0005")

    assert google.acks == []
    assert subscription_service.get_user_plan(db, user.id).code == "lite"


def test_verify_unknown_token_is_400(db, google):
    user = make_user(db, "play-6")

    with pytest.raises(subscription_service.BadRequestError):
        _verify(db, user.id, "playtoken-0006")


@pytest.mark.parametrize("state", ["PENDING", "PENDING_PURCHASE_CANCELED"])
def test_pending_purchase_is_400_and_not_acknowledged(db, google, state):
    user = make_user(db, f"play-7-{state}")
    google.sell(user.id, f"playtoken-0007-{state}", state=state)

    with pytest.raises(subscription_service.BadRequestError) as raised:
        _verify(db, user.id, f"playtoken-0007-{state}")

    assert str(raised.value) == subscription_service.PLAY_PENDING_MESSAGE
    assert google.acks == []
    assert subscription_service.get_user_plan(db, user.id).code == "lite"


def test_verify_rejects_another_members_obfuscated_account(db, google):
    """같은 구글 계정으로 다른 회원 계정에서 '구매 복원'을 눌러도 붙지 않는다 — 확인(acknowledge)도 하지 않는다."""
    buyer = make_user(db, "play-8")
    other = make_user(db, "play-9")
    google.sell(buyer.id, "playtoken-0008")

    with pytest.raises(PlayConflictError):
        _verify(db, other.id, "playtoken-0008")

    assert google.acks == []
    assert subscription_service.get_user_plan(db, other.id).code == "lite"


def test_verify_rejects_token_already_owned_by_another_member(db, google):
    """obfuscated 가 비어 있는 구매(앱 밖에서 시작)도 먼저 확인한 회원의 것이다 — 두 번째 회원은 409."""
    first = make_user(db, "play-10")
    second = make_user(db, "play-11")
    google.sell(first.id, "playtoken-0010", externalAccountIdentifiers={})

    _verify(db, first.id, "playtoken-0010")

    with pytest.raises(PlayConflictError):
        _verify(db, second.id, "playtoken-0010")

    assert subscription_service.get_user_plan(db, second.id).code == "lite"


def test_reverify_by_the_owner_is_idempotent(db, google):
    user = make_user(db, "play-12")
    google.sell(user.id, "playtoken-0012")

    _verify(db, user.id, "playtoken-0012")
    google.sell(user.id, "playtoken-0012", acknowledged=True)
    _verify(db, user.id, "playtoken-0012")

    assert _subscription(db, user.id).store_purchase_token == "playtoken-0012"
    assert len(google.acks) == 1


def test_linked_purchase_token_is_replaced_on_the_same_member(db, google):
    """월간 → 연간으로 바꾸면 Google 은 새 토큰을 주고 옛 토큰을 linkedPurchaseToken 으로 단다."""
    user = make_user(db, "play-13")
    google.sell(user.id, "playtoken-0013-old")
    _verify(db, user.id, "playtoken-0013-old")
    google.sell(user.id, "playtoken-0013-new", product=YEARLY, linkedPurchaseToken="playtoken-0013-old")

    _verify(db, user.id, "playtoken-0013-new", product_id=YEARLY)

    subscription = _subscription(db, user.id)
    assert subscription.store_purchase_token == "playtoken-0013-new"
    assert subscription.store_product_id == YEARLY
    # 옛 토큰의 알림은 이제 모르는 토큰이다 — Google 을 부르지 않고 버린다.
    google.get_calls.clear()
    assert subscription_service.handle_play_notification(db, _push("playtoken-0013-old")) == "unknown"
    assert google.get_calls == []


def test_linked_purchase_token_of_another_member_is_409(db, google):
    owner = make_user(db, "play-14")
    other = make_user(db, "play-15")
    google.sell(owner.id, "playtoken-0014-old")
    _verify(db, owner.id, "playtoken-0014-old")
    google.sell(other.id, "playtoken-0014-new", linkedPurchaseToken="playtoken-0014-old")

    with pytest.raises(PlayConflictError):
        _verify(db, other.id, "playtoken-0014-new")

    assert _subscription(db, owner.id).store_purchase_token == "playtoken-0014-old"


@pytest.mark.parametrize(
    ("state", "days", "status", "plan"),
    [
        ("CANCELED", 10, "canceled", "plus"),  # 해지 — 기간까지는 플러스
        ("IN_GRACE_PERIOD", 3, "past_due", "plus"),  # 유예 — 이용권 유지
        ("ON_HOLD", -2, "past_due", "lite"),  # 계정 보류 — 만료가 지나 무료
        ("PAUSED", -2, "past_due", "lite"),
        ("EXPIRED", -1, "canceled", "lite"),
    ],
)
def test_state_mapping(db, google, state, days, status, plan):
    user = make_user(db, f"play-16-{state}")
    google.sell(user.id, f"playtoken-0016-{state}", state=state, auto_renew=state != "CANCELED",
                acknowledged=True, expiry=datetime.now(UTC) + timedelta(days=days))

    _verify(db, user.id, f"playtoken-0016-{state}")

    assert _subscription(db, user.id).status == status
    # 행은 plus 그대로 두고 읽을 때 해석한다 (24장 규약).
    assert _subscription(db, user.id).plan_code == "plus"
    assert subscription_service.get_user_plan(db, user.id).code == plan


def test_expired_purchase_is_not_acknowledged(db, google):
    """끝난 구독(대개 확인하지 않아 자동 환불된 구매)은 확인할 것이 없다."""
    user = make_user(db, "play-17")
    google.sell(user.id, "playtoken-0017", state="EXPIRED", expiry=datetime.now(UTC) - timedelta(days=1))

    _verify(db, user.id, "playtoken-0017")

    assert google.acks == []


def test_unknown_expiry_never_grants_unlimited_plus(db, google):
    """만료 시각이 없는 응답이 무기한 플러스가 되면 안 된다 — 기간 NULL 유료는 만료되지 않는다."""
    user = make_user(db, "play-18")
    google.sell(user.id, "playtoken-0018", lineItems=[{"productId": MONTHLY}])

    _verify(db, user.id, "playtoken-0018")

    assert _subscription(db, user.id).current_period_end is not None
    assert subscription_service.get_user_plan(db, user.id).code == "lite"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-11-14T03:21:45.123Z", datetime(2026, 11, 14, 3, 21, 45, 123000, tzinfo=UTC)),
        ("2026-11-14T03:21:45.123456789Z", datetime(2026, 11, 14, 3, 21, 45, 123456, tzinfo=UTC)),
        ("2026-11-14T03:21:45Z", datetime(2026, 11, 14, 3, 21, 45, tzinfo=UTC)),
        ("2026-11-14T12:21:45+09:00", datetime(2026, 11, 14, 3, 21, 45, tzinfo=UTC)),
        ("garbage", None),
        (1731554505000, None),
    ],
)
def test_google_time_parsing(value, expected):
    """운영 파이썬 3.10 의 fromisoformat 은 Z·9자리 소수 초를 못 읽는다 — 그래도 읽혀야 한다."""
    assert subscription_service._from_google_time(value) == expected


def test_review_plus_refuses_play_subscribers(db, google):
    user = make_user(db, "play-19")
    google.sell(user.id, "playtoken-0019")
    _verify(db, user.id, "playtoken-0019")

    with pytest.raises(subscription_service.BadRequestError):
        subscription_service.grant_review_plus(db, user.id, datetime.now(UTC) + timedelta(days=30))

    assert _subscription(db, user.id).provider == "play"


# ---- 2) RTDN — 본문을 믿지 않는다 ----

def _push(purchase_token: str, *, package: str | None = None, notification_type: int = 13) -> dict:
    data = {
        "version": "1.0",
        "packageName": package or play_client.GOOGLE_PLAY_PACKAGE_NAME,
        "eventTimeMillis": "1760400000000",
        "subscriptionNotification": {
            "version": "1.0",
            "notificationType": notification_type,
            "purchaseToken": purchase_token,
            "subscriptionId": MONTHLY,
        },
    }
    return _envelope(data)


def _envelope(data: dict) -> dict:
    encoded = base64.b64encode(json.dumps(data).encode()).decode()
    return {"message": {"data": encoded, "messageId": "1"}, "subscription": "projects/caretable-play/subscriptions/x"}


def test_notification_for_unknown_token_does_not_call_google(db, google):
    assert subscription_service.handle_play_notification(db, _push("playtoken-unknown")) == "unknown"
    assert google.get_calls == []


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"hello": "world"},
        {"message": "x"},
        {"message": {"data": "!!!not-base64"}},
        {"message": {"data": base64.b64encode(b"[1, 2]").decode()}},
        _envelope({"version": "1.0", "packageName": "com.kcalai.kcalairn", "testNotification": {"version": "1.0"}}),
        _envelope({"packageName": "com.kcalai.kcalairn", "oneTimeProductNotification": {"purchaseToken": "x"}}),
    ],
)
def test_malformed_or_irrelevant_notification_is_ignored_without_google(db, google, body):
    assert subscription_service.handle_play_notification(db, body) == "ignored"
    assert google.get_calls == []


def test_notification_for_another_package_is_ignored_even_if_token_is_ours(db, google):
    user = make_user(db, "play-20")
    google.sell(user.id, "playtoken-0020")
    _verify(db, user.id, "playtoken-0020")
    google.get_calls.clear()

    result = subscription_service.handle_play_notification(
        db, _push("playtoken-0020", package="com.example.other")
    )

    assert result == "ignored"
    assert google.get_calls == []


def test_notification_updates_only_from_requery(db, google):
    """본문이 '환불됐다(REVOKED=12)'고 해도 Google 재조회가 활성이면 플러스 그대로다 (위조 본문 무력화)."""
    user = make_user(db, "play-21")
    google.sell(user.id, "playtoken-0021")
    _verify(db, user.id, "playtoken-0021")

    result = subscription_service.handle_play_notification(db, _push("playtoken-0021", notification_type=12))

    assert result == "updated"
    assert google.get_calls[-1] == "playtoken-0021"
    assert subscription_service.get_user_plan(db, user.id).code == "plus"


def test_notification_applies_expiry_seen_by_requery(db, google):
    user = make_user(db, "play-22")
    google.sell(user.id, "playtoken-0022")
    _verify(db, user.id, "playtoken-0022")
    # 본문은 '갱신됨(2)'이라고 하지만 Google 은 만료라고 한다 — Google 을 따른다.
    google.sell(user.id, "playtoken-0022", state="EXPIRED", acknowledged=True,
                expiry=datetime.now(UTC) - timedelta(minutes=1))

    subscription_service.handle_play_notification(db, _push("playtoken-0022", notification_type=2))

    assert subscription_service.get_user_plan(db, user.id).code == "lite"


def test_notification_token_unknown_to_google_leaves_ledger(db, google):
    user = make_user(db, "play-23")
    google.sell(user.id, "playtoken-0023")
    _verify(db, user.id, "playtoken-0023")
    del google.purchases["playtoken-0023"]

    assert subscription_service.handle_play_notification(db, _push("playtoken-0023")) == "not-found"
    assert subscription_service.get_user_plan(db, user.id).code == "plus"


# ---- 3) 갱신 배치는 Google Play 구독을 청구하지 않는다 ----

def test_renew_batch_never_charges_play_subscription(db, google, monkeypatch):
    """스토어 구독이 청구 대상에 섞이면 빌링키가 없어 멀쩡한 구독을 past_due 로 떨어뜨린다(30장)."""
    user = make_user(db, "play-24")
    google.sell(user.id, "playtoken-0024")
    _verify(db, user.id, "playtoken-0024")
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


# ---- 4) 라우트 ----

@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(billing_router, prefix="/api")
    add_service_error_handlers(app)
    app.dependency_overrides[get_db] = lambda: db

    with TestClient(app) as test_client:
        yield test_client


def _post_verify(client, purchase_token: str, product_id: str = MONTHLY):
    return client.post(
        "/api/billing/play/verify", json={"product_id": product_id, "purchase_token": purchase_token}
    )


def test_verify_route_returns_subscription(client, db, google):
    user = make_user(db, "play-25")
    google.sell(user.id, "playtoken-0025")
    client.app.dependency_overrides[get_current_user] = lambda: user

    body = _post_verify(client, "playtoken-0025").json()

    assert body["plan"]["code"] == "plus"
    assert body["provider"] == "play"
    assert body["store_product_id"] == MONTHLY
    assert body["next_billing_at"] is None


def test_verify_route_maps_conflict_to_409(client, db, google):
    buyer = make_user(db, "play-26")
    other = make_user(db, "play-27")
    google.sell(buyer.id, "playtoken-0026")
    client.app.dependency_overrides[get_current_user] = lambda: other

    response = _post_verify(client, "playtoken-0026")

    assert response.status_code == 409
    assert response.json() == {"detail": CONFLICT_MESSAGE}


def test_verify_route_maps_pending_and_non_plus_to_400(client, db, google):
    user = make_user(db, "play-28")
    google.sell(user.id, "playtoken-0028", state="PENDING")
    client.app.dependency_overrides[get_current_user] = lambda: user

    pending = _post_verify(client, "playtoken-0028")
    not_plus = _post_verify(client, "playtoken-0028", product_id="com.kcalai.kcalairn.other")

    assert pending.status_code == 400
    assert pending.json() == {"detail": subscription_service.PLAY_PENDING_MESSAGE}
    assert not_plus.status_code == 400


@pytest.mark.parametrize("purchase_token", ["a/../../x", "token with space", "", "x" * 513])
def test_verify_route_rejects_token_outside_url_charset(client, db, google, purchase_token):
    """purchaseToken 은 Google 조회 URL 경로에 실린다 — 토큰 문자가 아니면 조회 전에 422."""
    user = make_user(db, "play-29")
    client.app.dependency_overrides[get_current_user] = lambda: user

    assert _post_verify(client, purchase_token).status_code == 422
    assert google.get_calls == []


def test_verify_route_maps_unavailable_to_503(client, db, google):
    user = make_user(db, "play-30")
    google.error = PlayUnavailableError(play_client.UNAVAILABLE_MESSAGE)
    client.app.dependency_overrides[get_current_user] = lambda: user

    response = _post_verify(client, "playtoken-0030")

    assert response.status_code == 503
    assert response.json() == {"detail": play_client.UNAVAILABLE_MESSAGE}


def test_notification_route_is_unauthenticated_and_hides_result(client, db, google):
    user = make_user(db, "play-31")
    google.sell(user.id, "playtoken-0031")
    _verify(db, user.id, "playtoken-0031")

    known = client.post("/api/billing/play/notifications", json=_push("playtoken-0031"))
    unknown = client.post("/api/billing/play/notifications", json=_push("playtoken-unknown-31"))
    junk = client.post("/api/billing/play/notifications", json={"hello": "world"})
    odd = client.post("/api/billing/play/notifications", json={"message": 42, "subscription": 7})

    assert [r.status_code for r in (known, unknown, junk, odd)] == [200, 200, 200, 200]
    # 응답이 같아야 무인증 호출자가 토큰의 존재를 떠볼 수 없다.
    assert known.json() == unknown.json() == junk.json() == odd.json() == {}


def test_notification_route_503_when_google_requery_fails(client, db, google):
    user = make_user(db, "play-32")
    google.sell(user.id, "playtoken-0032")
    _verify(db, user.id, "playtoken-0032")
    google.error = PlayUnavailableError(play_client.UNAVAILABLE_MESSAGE)

    response = client.post("/api/billing/play/notifications", json=_push("playtoken-0032"))

    assert response.status_code == 503


# ---- 5) 어댑터 — 상태 분류 · 키·토큰 미유출 (requests 대체, Google 미호출) ----

OAUTH_TOKEN = "ya29.secret-oauth-access-token"
PURCHASE_TOKEN = "abcdefgh-secret-purchase-token-tail"


class _Response:
    def __init__(self, status_code: int, body: dict | None = None) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> dict:
        if self._body is None:
            raise ValueError("no body")
        return self._body


@pytest.fixture
def oauth(monkeypatch):
    monkeypatch.setattr(play_client, "_access_token", lambda: OAUTH_TOKEN)


def test_get_subscription_calls_v2_with_bearer(monkeypatch, oauth):
    seen = {}

    def fake_request(method, url, headers, timeout):
        seen.update(method=method, url=url, headers=headers)
        return _Response(200, {"subscriptionState": "SUBSCRIPTION_STATE_ACTIVE"})

    monkeypatch.setattr(play_client.requests, "request", fake_request)

    assert play_client.get_subscription(PURCHASE_TOKEN) == {"subscriptionState": "SUBSCRIPTION_STATE_ACTIVE"}
    assert seen["method"] == "GET"
    assert seen["url"] == (
        f"{play_client.BASE_URL}/{play_client.GOOGLE_PLAY_PACKAGE_NAME}/purchases/subscriptionsv2/tokens/"
        f"{PURCHASE_TOKEN}"
    )
    assert seen["headers"] == {"Authorization": f"Bearer {OAUTH_TOKEN}"}


@pytest.mark.parametrize("status_code", [404, 410])
def test_missing_or_long_expired_token_is_none(monkeypatch, oauth, caplog, status_code):
    monkeypatch.setattr(play_client.requests, "request", lambda *a, **k: _Response(status_code, {}))

    assert play_client.get_subscription(PURCHASE_TOKEN) is None
    # 로그에는 앞 8자만 남는다.
    assert PURCHASE_TOKEN not in caplog.text
    assert PURCHASE_TOKEN[:8] in caplog.text


@pytest.mark.parametrize("status_code", [400, 401, 403, 429, 500, 503])
def test_other_statuses_are_unavailable(monkeypatch, oauth, status_code):
    """401·403(서비스 계정 권한)·429·5xx 는 '구매 없음'이 아니라 '판단 못 함'이다 — 503."""
    monkeypatch.setattr(play_client.requests, "request", lambda *a, **k: _Response(status_code, {}))

    with pytest.raises(PlayUnavailableError):
        play_client.get_subscription(PURCHASE_TOKEN)


def test_acknowledge_posts_to_subscriptions_acknowledge(monkeypatch, oauth):
    seen = {}

    def fake_request(method, url, headers, timeout):
        seen.update(method=method, url=url)
        return _Response(200)  # 본문이 비어 있다

    monkeypatch.setattr(play_client.requests, "request", fake_request)

    assert play_client.acknowledge(MONTHLY, PURCHASE_TOKEN) is True
    assert seen["method"] == "POST"
    assert seen["url"].endswith(
        f"/{play_client.GOOGLE_PLAY_PACKAGE_NAME}/purchases/subscriptions/{MONTHLY}/tokens/{PURCHASE_TOKEN}:acknowledge"
    )


def test_network_failure_is_503_and_tokens_not_logged(monkeypatch, oauth, caplog):
    def failing_request(method, url, headers, timeout):
        raise requests.ConnectionError(f"boom {url} {headers['Authorization']}")

    monkeypatch.setattr(play_client.requests, "request", failing_request)

    with pytest.raises(PlayUnavailableError) as raised:
        play_client.get_subscription(PURCHASE_TOKEN)

    # 체인을 끊는다 — 상위 트레이스백에 URL(구매 토큰)·헤더(OAuth 토큰)가 실리지 않게.
    assert raised.value.__cause__ is None
    assert OAUTH_TOKEN not in caplog.text
    assert PURCHASE_TOKEN not in caplog.text
    assert "ConnectionError" in caplog.text


def test_service_logs_only_masked_token(db, google, caplog):
    buyer = make_user(db, "play-33")
    other = make_user(db, "play-34")
    google.sell(buyer.id, PURCHASE_TOKEN)

    with pytest.raises(PlayConflictError):
        _verify(db, other.id, PURCHASE_TOKEN)
    _verify(db, buyer.id, PURCHASE_TOKEN)

    assert PURCHASE_TOKEN not in caplog.text
    assert PURCHASE_TOKEN[:8] in caplog.text


def test_missing_service_account_is_503_without_calling_google(monkeypatch):
    monkeypatch.setattr(play_client, "GOOGLE_PLAY_SERVICE_ACCOUNT_B64", "")
    monkeypatch.setattr(play_client, "_credentials", None)
    monkeypatch.setattr(play_client.requests, "request", lambda *a, **k: pytest.fail("Google 을 부르면 안 된다"))

    with pytest.raises(PlayUnavailableError):
        play_client.get_subscription(PURCHASE_TOKEN)


@pytest.mark.parametrize(
    "encoded",
    ["%%%not-base64%%%", base64.b64encode(b"not json").decode(), base64.b64encode(b'{"type": "x"}').decode()],
)
def test_broken_service_account_is_503_with_chain_cut(monkeypatch, encoded):
    monkeypatch.setattr(play_client, "GOOGLE_PLAY_SERVICE_ACCOUNT_B64", encoded)
    monkeypatch.setattr(play_client, "_credentials", None)
    monkeypatch.setattr(requests.Session, "request", lambda *a, **k: pytest.fail("Google 을 부르면 안 된다"))

    with pytest.raises(PlayUnavailableError) as raised:
        play_client.get_subscription(PURCHASE_TOKEN)

    assert raised.value.__cause__ is None


def test_access_token_exchanges_scoped_jwt_with_short_timeout_and_is_reused(monkeypatch):
    """서비스 계정 → OAuth 토큰 교환이 androidpublisher 범위·짧은 타임아웃으로 나가고, 유효한 동안 재사용된다."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    info = {
        "type": "service_account",
        "project_id": "caretable-play",
        "private_key_id": "k1",
        "private_key": key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode(),
        "client_email": "play-publisher@caretable-play.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    monkeypatch.setattr(
        play_client, "GOOGLE_PLAY_SERVICE_ACCOUNT_B64", base64.b64encode(json.dumps(info).encode()).decode()
    )
    monkeypatch.setattr(play_client, "_credentials", None)
    calls = []

    def fake_session_request(self, method, url, data=None, headers=None, timeout=None, **kwargs):
        calls.append({"url": url, "timeout": timeout, "data": data})
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"access_token": OAUTH_TOKEN, "expires_in": 3600}).encode()
        return response

    monkeypatch.setattr(requests.Session, "request", fake_session_request)

    assert play_client._access_token() == OAUTH_TOKEN
    assert play_client._access_token() == OAUTH_TOKEN
    assert len(calls) == 1
    assert calls[0]["url"] == "https://oauth2.googleapis.com/token"
    assert calls[0]["timeout"] == play_client.PLAY_TIMEOUT_SECONDS
    body = calls[0]["data"].decode() if isinstance(calls[0]["data"], bytes) else calls[0]["data"]
    assertion = dict(pair.split("=", 1) for pair in body.split("&"))["assertion"]
    assert jwt.decode(assertion, options={"verify_signature": False})["scope"] == play_client.SCOPE
