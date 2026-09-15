"""환불 — 돈이 두 번 나가지 않는지 (`docs/LEGAL_COMPLIANCE.md` §2).

⚠️ **토스를 실제로 부르지 않는다.** 테스트 키라도 결제사 트래픽이고, 취소는 되돌릴 수 없다
(`CLAUDE.md`의 "토스 API 를 테스트에서 실제로 호출하지 않는다"). `toss_client` 를 통째로
monkeypatch 한다.

여기서 고정하려는 것은 **막는 조건**이다. 환불은 실패보다 **중복 성공**이 위험하다 —
돈이 두 번 나가면 사후에 알아채도 늦다.
"""

from datetime import datetime, timedelta

import pytest
from timeutil import UTC

from factories import make_payment
from services import billing_service, toss_client


@pytest.fixture
def paid(db, user):
    """승인 완료된 결제 1건."""
    return make_payment(
        db,
        user.id,
        f"order-refund-{user.id}",
        status=billing_service.PAYMENT_DONE,
        payment_key="test_payment_key",
        approved_at=datetime.now(UTC) - timedelta(days=1),
    )


class _Recorder:
    """토스 호출을 기록하는 대역."""

    def __init__(self, canceled_amount: int = 5000):
        self.calls: list[dict] = []
        self.canceled_amount = canceled_amount

    def __call__(self, payment_key, reason, *, amount=None, idempotency_key=None):
        self.calls.append(
            {
                "payment_key": payment_key,
                "reason": reason,
                "amount": amount,
                "idempotency_key": idempotency_key,
            }
        )
        return toss_client.CancelResult(
            status="CANCELED" if amount is None else "PARTIAL_CANCELED",
            canceled_amount=amount or self.canceled_amount,
            canceled_at=datetime.now(UTC),
        )


def test_full_refund_updates_the_ledger(db, paid, monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(toss_client, "cancel_payment", recorder)

    result = billing_service.refund_payment(db, paid.id, "고객 요청")

    assert result.status == billing_service.PAYMENT_CANCELED
    assert result.refunded_amount == 5000
    assert result.refund_reason == "고객 요청"
    assert result.canceled_at is not None
    # 원래 결제 금액은 그대로 남는다 — 얼마를 받았는지가 사라지면 안 된다.
    assert result.amount == 5000


def test_partial_refund_keeps_original_amount(db, paid, monkeypatch):
    monkeypatch.setattr(toss_client, "cancel_payment", _Recorder())

    result = billing_service.refund_payment(db, paid.id, "일할 환불", amount=2000)

    assert result.amount == 5000
    assert result.refunded_amount == 2000


def test_ledger_records_the_amount_toss_actually_canceled(db, paid, monkeypatch):
    """우리가 보낸 값이 아니라 **실제로 취소된 금액**이 남아야 한다."""
    recorder = _Recorder(canceled_amount=4321)
    monkeypatch.setattr(toss_client, "cancel_payment", recorder)

    result = billing_service.refund_payment(db, paid.id, "전액 환불")

    assert result.refunded_amount == 4321


# ── 막아야 하는 것들 ────────────────────────────────────────────────────────


def test_double_refund_is_blocked_before_calling_toss(db, paid, monkeypatch):
    """**돈이 두 번 나가는 것**을 우리 원장에서 먼저 막는다."""
    recorder = _Recorder()
    monkeypatch.setattr(toss_client, "cancel_payment", recorder)

    billing_service.refund_payment(db, paid.id, "첫 환불")

    with pytest.raises(ValueError, match="이미 환불"):
        billing_service.refund_payment(db, paid.id, "두 번째 시도")

    assert len(recorder.calls) == 1, "두 번째 시도가 토스까지 갔다"


def test_unpaid_payment_cannot_be_refunded(db, user, monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(toss_client, "cancel_payment", recorder)
    payment = make_payment(
        db, user.id, f"order-ready-{user.id}", status=billing_service.PAYMENT_READY
    )

    with pytest.raises(ValueError, match="승인 완료된 결제만"):
        billing_service.refund_payment(db, payment.id, "잘못된 요청")

    assert not recorder.calls


def test_refund_cannot_exceed_the_charged_amount(db, paid, monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(toss_client, "cancel_payment", recorder)

    with pytest.raises(ValueError, match="결제 금액을 넘을 수 없습니다"):
        billing_service.refund_payment(db, paid.id, "과다 환불", amount=9999)

    assert not recorder.calls


def test_missing_payment_raises(db, monkeypatch):
    monkeypatch.setattr(toss_client, "cancel_payment", _Recorder())

    with pytest.raises(ValueError, match="찾을 수 없습니다"):
        billing_service.refund_payment(db, 99999999, "없는 결제")


# ── 멱등키 ──────────────────────────────────────────────────────────────────


def test_idempotency_key_is_fixed_per_payment(db, paid, monkeypatch):
    """네트워크 오류로 재시도해도 토스가 중복 처리하지 않도록 **결제마다 고정 키**를 쓴다."""
    recorder = _Recorder()
    monkeypatch.setattr(toss_client, "cancel_payment", recorder)

    billing_service.refund_payment(db, paid.id, "고객 요청")

    assert recorder.calls[0]["idempotency_key"] == f"refund-{paid.order_id}"


def test_payment_key_is_passed_but_never_logged(db, paid, monkeypatch, caplog):
    """결제키는 재청구 자격증명이라 로그에 남기지 않는다."""
    monkeypatch.setattr(toss_client, "cancel_payment", _Recorder())

    with caplog.at_level("INFO"):
        billing_service.refund_payment(db, paid.id, "고객 요청")

    assert "test_payment_key" not in caplog.text
