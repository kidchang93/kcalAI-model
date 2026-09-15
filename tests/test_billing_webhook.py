"""토스 웹훅 → 원장 동기화 회귀 (DATA_MODEL.md 29장).

이 파일이 지키는 명제는 하나다: **웹훅 본문으로는 원장을 바꿀 수 없다.** 결제 웹훅에는 서명이
없어 누구나 같은 모양의 JSON 을 보낼 수 있으므로, 본문이 "취소됐다"고 말해도 토스 조회가
"승인 상태"라고 하면 원장은 그대로여야 한다 (`test_forged_cancel_does_not_touch_ledger`).

토스 API 는 호출하지 않는다 — `toss_client.get_payment_by_order_id` 를 monkeypatch 로 대체한다.

카카오 회원번호는 다른 테스트와 겹치지 않도록 8400000xxx 대역을 쓴다.
"""

from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.billing_api import router
from database import get_db
from factories import make_payment, make_user
from models.subscription_model import UserSubscription
from services import billing_service, toss_client
from services.toss_client import PaymentSnapshot, TossError, TossNotConfiguredError
from timeutil import UTC

PRO_PRICE = 5000


def _add_payment(db, user_id: int | None, order_id: str, **kwargs):
    # 이 파일의 결제는 기본적으로 "이미 승인된" 건이다 — make_payment 의 기본값과 다르다.
    kwargs.setdefault("payment_key", "pay_test_key")
    kwargs.setdefault("amount", PRO_PRICE)
    kwargs.setdefault("approved_at", datetime.now(UTC))
    return make_payment(db, user_id, order_id, **kwargs)


def _snapshot(order_id: str, status: str, **kwargs) -> PaymentSnapshot:
    total = kwargs.pop("total_amount", PRO_PRICE)
    balance = kwargs.pop("balance_amount", total)
    return PaymentSnapshot(
        order_id=order_id,
        payment_key=kwargs.pop("payment_key", "pay_test_key"),
        status=status,
        total_amount=total,
        balance_amount=balance,
        method=kwargs.pop("method", "카드"),
        approved_at=kwargs.pop("approved_at", datetime.now(UTC)),
        canceled_amount=max(total - balance, 0),
        canceled_at=kwargs.pop("canceled_at", None),
        cancel_reason=kwargs.pop("cancel_reason", None),
    )


class _LookupStub:
    """조회 대역. **몇 번 불렸는지**가 계약의 일부다 — 모르는 주문에는 부르면 안 된다."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.snapshots: dict[str, PaymentSnapshot] = {}
        self.error: Exception | None = None

    def get_payment_by_order_id(self, order_id: str) -> PaymentSnapshot:
        self.calls.append(order_id)

        if self.error is not None:
            raise self.error

        return self.snapshots[order_id]


@pytest.fixture
def lookup(monkeypatch) -> _LookupStub:
    stub = _LookupStub()
    monkeypatch.setattr(toss_client, "get_payment_by_order_id", stub.get_payment_by_order_id)
    return stub


# ---- 1) 본문을 믿지 않는다 ----

def test_forged_cancel_does_not_touch_ledger(db, lookup):
    """위조 웹훅의 핵심 시나리오 — 본문은 "취소"라고 하지만 토스는 승인 상태다."""
    user = make_user(db, "8400000001")
    payment = _add_payment(db, user.id, "ord_forge", status="done")
    lookup.snapshots["ord_forge"] = _snapshot("ord_forge", toss_client.STATUS_DONE)

    result = billing_service.sync_payment_from_toss(db, "ord_forge")

    assert result == "noop"
    db.refresh(payment)
    assert payment.status == "done"
    assert payment.refunded_amount is None
    assert payment.canceled_at is None


def test_unknown_order_does_not_call_toss(db, lookup):
    """모르는 주문번호로는 결제사 조회를 유발할 수 없다 (증폭 방지)."""
    result = billing_service.sync_payment_from_toss(db, "ord_not_ours")

    assert result == "unknown"
    assert lookup.calls == []


# ---- 2) 취소 반영 (상점관리자 수동 취소) ----

def test_cancel_is_written_to_ledger(db, lookup):
    user = make_user(db, "8400000002")
    payment = _add_payment(db, user.id, "ord_cancel", status="done")
    canceled_at = datetime.now(UTC)
    lookup.snapshots["ord_cancel"] = _snapshot(
        "ord_cancel",
        toss_client.STATUS_CANCELED,
        balance_amount=0,
        canceled_at=canceled_at,
        cancel_reason="고객 요청",
    )

    result = billing_service.sync_payment_from_toss(db, "ord_cancel")

    assert result == "canceled"
    db.refresh(payment)
    assert payment.status == "canceled"
    assert payment.refunded_amount == PRO_PRICE
    assert payment.refund_reason == "고객 요청"
    assert payment.canceled_at is not None


def test_partial_cancel_uses_balance_not_total(db, lookup):
    """부분 취소는 **잔액 기준**으로 누계를 낸다. 결제 금액(amount)은 그대로 남는다."""
    user = make_user(db, "8400000003")
    payment = _add_payment(db, user.id, "ord_partial", status="done")
    lookup.snapshots["ord_partial"] = _snapshot(
        "ord_partial", toss_client.STATUS_PARTIAL_CANCELED, balance_amount=2000
    )

    billing_service.sync_payment_from_toss(db, "ord_partial")

    db.refresh(payment)
    assert payment.status == "canceled"
    assert payment.refunded_amount == 3000
    assert payment.amount == PRO_PRICE


def test_repeated_cancel_webhook_is_idempotent(db, lookup):
    """토스는 최대 7회 재전송한다 — 같은 취소를 다시 받아도 기록이 흔들리지 않는다."""
    user = make_user(db, "8400000004")
    payment = _add_payment(db, user.id, "ord_dup", status="done")
    lookup.snapshots["ord_dup"] = _snapshot(
        "ord_dup", toss_client.STATUS_CANCELED, balance_amount=0, cancel_reason="고객 요청"
    )

    first = billing_service.sync_payment_from_toss(db, "ord_dup")
    db.refresh(payment)
    first_canceled_at = payment.canceled_at
    second = billing_service.sync_payment_from_toss(db, "ord_dup")

    assert (first, second) == ("canceled", "noop")
    db.refresh(payment)
    assert payment.canceled_at == first_canceled_at
    assert payment.refunded_amount == PRO_PRICE


def test_cancel_does_not_revoke_subscription(db, lookup):
    """환불과 이용권 회수는 다른 판단이다 (`refund_payment` 와 같은 규약)."""
    user = make_user(db, "8400000005")
    _add_payment(db, user.id, "ord_keep", status="done")
    subscription = billing_service.get_subscription(db, user.id)
    period_end = datetime.now(UTC) + timedelta(days=20)
    subscription.plan_code = "pro"
    subscription.status = "active"
    subscription.current_period_end = period_end
    db.commit()
    lookup.snapshots["ord_keep"] = _snapshot(
        "ord_keep", toss_client.STATUS_CANCELED, balance_amount=0
    )

    billing_service.sync_payment_from_toss(db, "ord_keep")

    db.refresh(subscription)
    assert subscription.plan_code == "pro"
    assert subscription.status == "active"


# ---- 3) 승인 복구 (돈은 나갔는데 기록이 실패인 상태) ----

def test_done_webhook_recovers_failed_ledger_and_activates(db, lookup):
    user = make_user(db, "8400000006")
    payment = _add_payment(
        db, user.id, "ord_recover", status="failed", payment_key=None, approved_at=None
    )
    approved_at = datetime.now(UTC)
    lookup.snapshots["ord_recover"] = _snapshot(
        "ord_recover", toss_client.STATUS_DONE, payment_key="pay_recovered", approved_at=approved_at
    )

    result = billing_service.sync_payment_from_toss(db, "ord_recover")

    assert result == "done"
    db.refresh(payment)
    assert payment.status == "done"
    assert payment.payment_key == "pay_recovered"
    assert payment.fail_code is None
    assert payment.fail_reason is None
    # 결제된 만큼 구독도 살아나야 한다 — 원장만 고치면 사용자는 돈 내고 무료로 남는다.
    subscription = db.scalar(
        select(UserSubscription).where(UserSubscription.user_id == user.id)
    )
    assert subscription.plan_code == "pro"
    assert subscription.status == "active"
    assert subscription.current_period_end is not None


def test_done_webhook_does_not_extend_active_subscription(db, lookup):
    """이미 반영된 결제의 재전송이 기간을 두 번 늘리면 안 된다."""
    user = make_user(db, "8400000007")
    _add_payment(db, user.id, "ord_already", status="done")
    subscription = billing_service.get_subscription(db, user.id)
    period_end = datetime.now(UTC) + timedelta(days=20)
    subscription.plan_code = "pro"
    subscription.status = "active"
    subscription.current_period_end = period_end
    db.commit()
    lookup.snapshots["ord_already"] = _snapshot("ord_already", toss_client.STATUS_DONE)

    result = billing_service.sync_payment_from_toss(db, "ord_already")

    assert result == "noop"
    db.refresh(subscription)
    assert subscription.current_period_end == period_end


def test_done_webhook_on_anonymized_ledger_skips_subscription(db, lookup):
    """탈퇴로 익명화된 원장(user_id=NULL)은 붙일 구독이 없다 — 기록만 바로잡는다."""
    payment = _add_payment(db, None, "ord_anon", status="failed", payment_key=None)
    lookup.snapshots["ord_anon"] = _snapshot("ord_anon", toss_client.STATUS_DONE)

    result = billing_service.sync_payment_from_toss(db, "ord_anon")

    assert result == "done"
    db.refresh(payment)
    assert payment.status == "done"


# ---- 4) 승인되지 못하고 끝난 결제 ----

@pytest.mark.parametrize("status", [toss_client.STATUS_ABORTED, toss_client.STATUS_EXPIRED])
def test_dead_status_closes_ready_ledger(db, lookup, status):
    user = make_user(db, f"84000001{status[:2]}")
    payment = _add_payment(
        db, user.id, f"ord_dead_{status}", status="ready", payment_key=None, approved_at=None
    )
    lookup.snapshots[f"ord_dead_{status}"] = _snapshot(f"ord_dead_{status}", status)

    result = billing_service.sync_payment_from_toss(db, f"ord_dead_{status}")

    assert result == "failed"
    db.refresh(payment)
    assert payment.status == "failed"
    assert payment.fail_code == status


def test_dead_status_does_not_overwrite_done(db, lookup):
    """승인된 결제를 뒤늦은 실패 알림이 뒤집지 못한다."""
    user = make_user(db, "8400000008")
    payment = _add_payment(db, user.id, "ord_done_keep", status="done")
    lookup.snapshots["ord_done_keep"] = _snapshot("ord_done_keep", toss_client.STATUS_ABORTED)

    result = billing_service.sync_payment_from_toss(db, "ord_done_keep")

    assert result == "noop"
    db.refresh(payment)
    assert payment.status == "done"


def test_in_progress_status_leaves_ledger_alone(db, lookup):
    user = make_user(db, "8400000009")
    payment = _add_payment(db, user.id, "ord_progress", status="ready", payment_key=None)
    lookup.snapshots["ord_progress"] = _snapshot("ord_progress", "IN_PROGRESS")

    result = billing_service.sync_payment_from_toss(db, "ord_progress")

    assert result == "pending"
    db.refresh(payment)
    assert payment.status == "ready"


# ---- 5) 라우트 (재전송 정책은 상태코드로 표현된다) ----

@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db

    with TestClient(app) as test_client:
        yield test_client


def _post_webhook(client, **body):
    return client.post("/api/billing/webhook", json=body)


def test_webhook_route_requires_no_auth(db, client, lookup):
    user = make_user(db, "8400000010")
    payment = _add_payment(db, user.id, "ord_route", status="done")
    lookup.snapshots["ord_route"] = _snapshot(
        "ord_route", toss_client.STATUS_CANCELED, balance_amount=0
    )

    response = _post_webhook(
        client, eventType="PAYMENT_STATUS_CHANGED", data={"orderId": "ord_route"}
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    db.refresh(payment)
    assert payment.status == "canceled"


def test_webhook_response_hides_result(db, client, lookup):
    """존재하지 않는 주문과 처리된 주문의 응답이 구별되면 안 된다 (존재 은닉)."""
    response = _post_webhook(
        client, eventType="PAYMENT_STATUS_CHANGED", data={"orderId": "ord_nope"}
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    assert lookup.calls == []


def test_unhandled_event_type_is_ignored(client, lookup):
    response = _post_webhook(client, eventType="BILLING_DELETED", billingKey="bk_x")

    assert response.status_code == 200
    assert lookup.calls == []


def test_missing_order_id_is_ignored(client, lookup):
    response = _post_webhook(client, eventType="PAYMENT_STATUS_CHANGED", data={"status": "DONE"})

    assert response.status_code == 200
    assert lookup.calls == []


def test_unknown_body_shape_does_not_422(client, lookup):
    """모르는 모양이어도 422 로 거절하지 않는다 — 거절하면 7번 재전송된다."""
    response = client.post("/api/billing/webhook", json={"hello": "world"})

    assert response.status_code == 200
    assert lookup.calls == []


def test_order_unknown_to_toss_closes_without_retransmission(db, client, lookup):
    """토스가 모르는 주문(404)은 재전송해도 답이 같다 — 200 으로 닫고 원장은 그대로 둔다."""
    user = make_user(db, "8400000013")
    payment = _add_payment(db, user.id, "ord_ghost", status="ready", payment_key=None)
    lookup.error = TossError("결제에 실패했습니다.", code=toss_client.ERROR_NOT_FOUND_PAYMENT)

    response = _post_webhook(
        client, eventType="PAYMENT_STATUS_CHANGED", data={"orderId": "ord_ghost"}
    )

    assert response.status_code == 200
    db.refresh(payment)
    assert payment.status == "ready"


def test_toss_lookup_failure_returns_502_for_retransmission(db, client, lookup):
    """조회에 실패했으면 **아직 판단하지 못한 것**이다 — 200 을 주면 알림이 영영 사라진다."""
    user = make_user(db, "8400000011")
    _add_payment(db, user.id, "ord_retry", status="done")
    lookup.error = TossError("결제 서버와 통신하지 못했습니다. 잠시 후 다시 시도해주세요.")

    response = _post_webhook(
        client, eventType="CANCEL_STATUS_CHANGED", data={"orderId": "ord_retry"}
    )

    assert response.status_code == 502


def test_toss_not_configured_returns_503_for_retransmission(db, client, lookup):
    user = make_user(db, "8400000012")
    _add_payment(db, user.id, "ord_noconf", status="done")
    lookup.error = TossNotConfiguredError("결제 서비스를 준비 중입니다. 잠시 후 다시 시도해주세요.")

    response = _post_webhook(
        client, eventType="PAYMENT_STATUS_CHANGED", data={"orderId": "ord_noconf"}
    )

    assert response.status_code == 503
