"""자동결제(토스 빌링) 회귀 (DATA_MODEL.md 24장).

**토스 API 는 절대 호출하지 않는다** — `toss_client` 의 함수를 monkeypatch 로 전부 대체한다.
실제 호출은 테스트 토큰이라도 결제사 트래픽이고, 네트워크에 의존하는 순간 회귀가 아니게 된다.
`_toss` 픽스처가 기본으로 성공 목을 깔고, 실패 케이스만 개별 테스트가 덮어쓴다.

카카오 회원번호는 다른 테스트와 겹치지 않도록 8300000xxx 대역을 쓴다.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, text

from models.auth_model import User
from models.subscription_model import BillingKey, Payment, UserSubscription
from services import billing_service, subscription_service, toss_client
from services.toss_client import ChargeResult, IssuedBillingKey, TossError, TossNotConfiguredError
from timeutil import UTC

PRO_PRICE = 5000


def _make_user(db, kakao_id: str) -> User:
    user = User(kakao_id=kakao_id, nickname="테스터")
    db.add(user)
    db.commit()
    return user


class _TossStub:
    """토스 어댑터 대역. 호출 인자를 기록해 '서버가 정한 금액'을 검증할 수 있게 한다."""

    def __init__(self) -> None:
        self.issued_calls: list[tuple[str, str]] = []
        self.charge_calls: list[dict] = []
        self.issue_error: Exception | None = None
        self.charge_error: Exception | None = None

    def issue_billing_key(self, auth_key: str, customer_key: str) -> IssuedBillingKey:
        self.issued_calls.append((auth_key, customer_key))

        if self.issue_error is not None:
            raise self.issue_error

        return IssuedBillingKey(
            billing_key="bk_test_secret_value",
            card_company="신한",
            card_number="433012******1234",
            card_type="신용",
        )

    def charge_billing(
        self, billing_key: str, customer_key: str, amount: int, order_id: str, order_name: str
    ) -> ChargeResult:
        self.charge_calls.append(
            {
                "billing_key": billing_key,
                "customer_key": customer_key,
                "amount": amount,
                "order_id": order_id,
                "order_name": order_name,
            }
        )

        if self.charge_error is not None:
            raise self.charge_error

        return ChargeResult(
            payment_key="pay_test_key",
            status="DONE",
            method="카드",
            approved_at=datetime.now(UTC),
        )


@pytest.fixture
def toss(monkeypatch) -> _TossStub:
    stub = _TossStub()
    monkeypatch.setattr(toss_client, "issue_billing_key", stub.issue_billing_key)
    monkeypatch.setattr(toss_client, "charge_billing", stub.charge_billing)
    # 키 미설정 환경(로컬·CI)에서도 결제 흐름을 돌리기 위해 구성 검사만 통과시킨다.
    monkeypatch.setattr(toss_client, "ensure_configured", lambda: None)
    monkeypatch.setattr(toss_client, "is_configured", lambda: True)
    monkeypatch.setattr(toss_client, "TOSS_CLIENT_KEY", "test_ck_stub")
    return stub


# ---- 1) 결제 준비 (checkout) ----

def test_checkout_returns_server_decided_amount(db, toss):
    user = _make_user(db, "8300000001")

    checkout = billing_service.start_checkout(db, user.id, "pro")

    # 금액은 클라이언트가 아니라 plans.price_krw 가 정한다.
    assert checkout["amount"] == PRO_PRICE
    assert checkout["plan_code"] == "pro"
    assert checkout["client_key"] == "test_ck_stub"
    # customerKey 는 추측 불가여야 하고 개인정보(user_id 등)를 담으면 안 된다.
    assert checkout["customer_key"].startswith("cus_")
    assert str(user.id) not in checkout["customer_key"].removeprefix("cus_")


def test_checkout_rejects_free_plan(db, toss):
    user = _make_user(db, "8300000002")

    with pytest.raises(ValueError):
        billing_service.start_checkout(db, user.id, "lite")


def test_checkout_rejects_unknown_plan(db, toss):
    user = _make_user(db, "8300000003")

    with pytest.raises(ValueError):
        billing_service.start_checkout(db, user.id, "enterprise")


def test_checkout_without_toss_keys_raises_not_configured(db, monkeypatch):
    user = _make_user(db, "8300000004")
    monkeypatch.setattr(toss_client, "is_configured", lambda: False)

    # 라우트가 503 으로 변환한다 — 장애가 아니라 미구성이다.
    with pytest.raises(TossNotConfiguredError):
        billing_service.start_checkout(db, user.id, "pro")


def test_checkout_reuses_existing_customer_key(db, toss):
    user = _make_user(db, "8300000005")
    billing_service.confirm_billing(db, user.id, "auth_1", "cus_fixed", "pro")

    checkout = billing_service.start_checkout(db, user.id, "premium")

    # 같은 회원이 토스 쪽에서 여러 구매자로 갈라지지 않아야 한다.
    assert checkout["customer_key"] == "cus_fixed"


# ---- 2) 카드 등록 + 최초 청구 (confirm) ----

def test_confirm_activates_subscription_and_records_payment(db, toss):
    user = _make_user(db, "8300000010")

    subscription = billing_service.confirm_billing(db, user.id, "auth_1", "cus_1", "pro")

    assert subscription.plan_code == "pro"
    assert subscription.status == "active"
    assert subscription.cancel_at_period_end is False
    # 기간 = 지금 + 1개월, 다음 청구 = 기간 종료와 같은 시각(자동갱신).
    assert subscription.next_billing_at == subscription.current_period_end
    assert subscription.current_period_end > datetime.now(UTC) + timedelta(days=27)

    payment = db.scalar(select(Payment).where(Payment.user_id == user.id))
    assert payment.status == "done"
    assert payment.amount == PRO_PRICE
    assert payment.payment_key == "pay_test_key"
    assert payment.method == "카드"
    assert payment.approved_at is not None
    assert payment.fail_code is None

    # 청구 금액은 서버가 정한 값이어야 한다 (요청 본문에는 금액 자체가 없다).
    assert toss.charge_calls[0]["amount"] == PRO_PRICE
    assert toss.charge_calls[0]["order_id"] == payment.order_id


def test_confirm_stores_billing_key_encrypted(db, toss):
    user = _make_user(db, "8300000011")

    billing_service.confirm_billing(db, user.id, "auth_1", "cus_1", "pro")

    billing = db.scalar(select(BillingKey).where(BillingKey.user_id == user.id))
    # ORM 은 EncryptedString 이 복호화해 평문을 준다.
    assert billing.billing_key == "bk_test_secret_value"
    assert billing.card_company == "신한"
    assert billing.card_number == "433012******1234"

    # DB 에는 암호문만 있어야 한다 — 원문 컬럼을 직접 읽어 확인한다.
    raw = db.execute(
        text("SELECT billing_key FROM billing_keys WHERE user_id = :user_id"),
        {"user_id": user.id},
    ).scalar_one()
    assert raw != "bk_test_secret_value"
    assert "bk_test_secret_value" not in raw


def test_confirm_charge_failure_does_not_activate_subscription(db, toss):
    user = _make_user(db, "8300000012")
    toss.charge_error = TossError("카드 잔액이 부족합니다.", code="NOT_ENOUGH_BALANCE")

    with pytest.raises(TossError):
        billing_service.confirm_billing(db, user.id, "auth_1", "cus_1", "pro")

    # 결제 안 된 Pro 가 생기면 안 된다. 청구 실패는 구독 행을 만들지도 않는다(무료 자기치유).
    subscription = subscription_service.get_subscription(db, user.id)
    assert subscription.plan_code == "lite"
    assert subscription.current_period_end is None
    assert subscription_service.get_user_plan(db, user.id).code == "lite"

    # 실패도 원장에는 남는다. fail_code(결제사 코드)는 DB 에만, fail_reason 은 사용자용 문구다.
    payment = db.scalar(select(Payment).where(Payment.user_id == user.id))
    assert payment.status == "failed"
    assert payment.fail_code == "NOT_ENOUGH_BALANCE"
    assert payment.fail_reason == "카드 잔액이 부족합니다."
    assert payment.payment_key is None


def test_confirm_rejects_free_plan(db, toss):
    user = _make_user(db, "8300000013")

    with pytest.raises(ValueError):
        billing_service.confirm_billing(db, user.id, "auth_1", "cus_1", "lite")

    # 검증 실패면 토스를 부르지도 않는다.
    assert toss.issued_calls == []


# ---- 3) 해지 ----

def test_cancel_keeps_paid_plan_until_period_end(db, toss):
    user = _make_user(db, "8300000020")
    billing_service.confirm_billing(db, user.id, "auth_1", "cus_1", "pro")
    period_end = db.scalar(
        select(UserSubscription.current_period_end).where(UserSubscription.user_id == user.id)
    )

    subscription = billing_service.cancel_billing(db, user.id)

    assert subscription.status == "canceled"
    assert subscription.cancel_at_period_end is True
    # 다음 청구는 사라지지만 기간은 그대로다 — 이미 받은 돈의 이용권을 회수하지 않는다.
    assert subscription.next_billing_at is None
    assert subscription.current_period_end == period_end
    assert subscription_service.get_user_plan(db, user.id).code == "pro"


def test_cancel_free_plan_is_rejected(db, toss):
    user = _make_user(db, "8300000021")

    with pytest.raises(ValueError):
        billing_service.cancel_billing(db, user.id)


# ---- 4) 만료 강등 ----

def test_expired_paid_subscription_reads_as_free_plan(db, toss):
    user = _make_user(db, "8300000030")
    billing_service.confirm_billing(db, user.id, "auth_1", "cus_1", "premium")
    subscription = db.scalar(select(UserSubscription).where(UserSubscription.user_id == user.id))

    # 기간이 지났다 — 행은 premium 그대로지만 해석은 lite 여야 한다.
    subscription.current_period_end = datetime.now(UTC) - timedelta(minutes=1)
    subscription.next_billing_at = None
    db.commit()

    assert subscription_service.get_user_plan(db, user.id).code == "lite"
    # 행은 보존된다 — 갱신·이력이 살아 있어야 한다.
    assert subscription.plan_code == "premium"

    view = subscription_service.my_subscription_view(db, user.id)
    assert view["plan"]["code"] == "lite"
    # 쿼터도 만료를 존중한다 (premium 100 이 아니라 lite 한도).
    assert view["vision_usage"]["limit"] == subscription_service.get_plan(db, "lite").daily_vision_quota


def test_active_paid_subscription_is_not_downgraded(db, toss):
    user = _make_user(db, "8300000031")
    billing_service.confirm_billing(db, user.id, "auth_1", "cus_1", "pro")

    assert subscription_service.get_user_plan(db, user.id).code == "pro"


def test_paid_plan_without_period_end_has_no_expiry(db, toss):
    # 결제 이전에 부여된 구독(가입 시 plan_code 선택)은 만료 개념이 없다 — 강등하면 안 된다.
    user = _make_user(db, "8300000032")
    subscription = subscription_service.get_subscription(db, user.id)
    subscription.plan_code = "premium"
    subscription.current_period_end = None
    db.commit()

    assert subscription_service.get_user_plan(db, user.id).code == "premium"


# ---- 5) PUT /api/me/subscription 제한 ----

def test_change_plan_blocks_paid_upgrade(db, toss):
    user = _make_user(db, "8300000040")

    with pytest.raises(ValueError, match="결제"):
        subscription_service.change_plan(db, user.id, "pro")

    assert subscription_service.get_user_plan(db, user.id).code == "lite"


def test_change_plan_allows_downgrade_to_free(db, toss):
    user = _make_user(db, "8300000041")
    billing_service.confirm_billing(db, user.id, "auth_1", "cus_1", "pro")

    subscription = subscription_service.change_plan(db, user.id, "lite")

    assert subscription.plan_code == "lite"
    # 무료로 내려가면 청구 예정이 남으면 안 된다 — 갱신 배치가 집어 들면 무료 회원이 청구된다.
    assert subscription.next_billing_at is None
    assert subscription.current_period_end is None


# ---- 6) 갱신 배치 ----

def _make_due_subscription(db, kakao_id: str, plan_code: str = "pro") -> User:
    user = _make_user(db, kakao_id)
    billing_service.confirm_billing(db, user.id, "auth_1", f"cus_{kakao_id}", plan_code)
    subscription = db.scalar(select(UserSubscription).where(UserSubscription.user_id == user.id))
    # 청구 예정일이 지난 상태로 만든다 (기간 종료 = 청구 예정 = 1분 전).
    due = datetime.now(UTC) - timedelta(minutes=1)
    subscription.current_period_end = due
    subscription.next_billing_at = due
    db.commit()
    return user


def test_renew_batch_extends_period_on_success(db, toss):
    user = _make_due_subscription(db, "8300000050")

    result = billing_service.charge_due_subscriptions(db)

    assert result["charged"] >= 1
    subscription = db.scalar(select(UserSubscription).where(UserSubscription.user_id == user.id))
    assert subscription.status == "active"
    assert subscription.current_period_end > datetime.now(UTC) + timedelta(days=27)
    assert subscription.next_billing_at == subscription.current_period_end
    # 최초 청구 + 갱신 청구 = 2건.
    payments = list(db.scalars(select(Payment).where(Payment.user_id == user.id)).all())
    assert len(payments) == 2
    assert all(payment.status == "done" for payment in payments)
    assert all(payment.amount == PRO_PRICE for payment in payments)


def test_renew_batch_is_idempotent(db, toss):
    user = _make_due_subscription(db, "8300000051")
    billing_service.charge_due_subscriptions(db)
    charge_count = len(toss.charge_calls)
    period_end = db.scalar(
        select(UserSubscription.current_period_end).where(UserSubscription.user_id == user.id)
    )

    # 같은 날 다시 돌려도 이미 청구한 구독은 대상이 아니다 (next_billing_at 이 미래).
    billing_service.charge_due_subscriptions(db)

    assert len(toss.charge_calls) == charge_count
    assert (
        db.scalar(
            select(UserSubscription.current_period_end).where(
                UserSubscription.user_id == user.id
            )
        )
        == period_end
    )
    assert len(list(db.scalars(select(Payment).where(Payment.user_id == user.id)).all())) == 2


def test_done_payment_is_not_applied_twice(db, toss):
    # 멱등의 마지막 방어선 — 이미 done 인 주문은 재반영하지 않는다(기간 이중 연장 방지).
    user = _make_user(db, "8300000052")
    billing_service.confirm_billing(db, user.id, "auth_1", "cus_1", "pro")
    payment = db.scalar(select(Payment).where(Payment.user_id == user.id))

    applied = billing_service._mark_payment_done(
        payment,
        ChargeResult(payment_key="pay_other", status="DONE", method="카드", approved_at=None),
    )

    assert applied is False
    assert payment.payment_key == "pay_test_key"


def test_renew_batch_marks_past_due_and_retries_next_day(db, toss):
    user = _make_due_subscription(db, "8300000053")
    period_end = db.scalar(
        select(UserSubscription.current_period_end).where(UserSubscription.user_id == user.id)
    )
    toss.charge_error = TossError("카드사에서 결제를 거절했습니다.", code="REJECT_CARD_COMPANY")

    result = billing_service.charge_due_subscriptions(db)

    assert result["failed"] >= 1
    subscription = db.scalar(select(UserSubscription).where(UserSubscription.user_id == user.id))
    assert subscription.status == "past_due"
    # 기간은 줄이지 않는다(유예). 재시도는 다음날.
    assert subscription.current_period_end == period_end
    assert subscription.next_billing_at > datetime.now(UTC)
    assert subscription.next_billing_at < datetime.now(UTC) + timedelta(days=2)

    payment = db.scalar(
        select(Payment).where(Payment.user_id == user.id).order_by(Payment.id.desc())
    )
    assert payment.status == "failed"
    assert payment.fail_code == "REJECT_CARD_COMPANY"


def test_renew_batch_gives_up_after_retry_window(db, toss):
    user = _make_due_subscription(db, "8300000054")
    subscription = db.scalar(select(UserSubscription).where(UserSubscription.user_id == user.id))
    # 재시도 창(기간 종료 + 3일)을 넘긴 시점의 실패.
    subscription.current_period_end = datetime.now(UTC) - timedelta(days=5)
    subscription.next_billing_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    toss.charge_error = TossError("카드사에서 결제를 거절했습니다.", code="REJECT_CARD_COMPANY")

    billing_service.charge_due_subscriptions(db)

    db.refresh(subscription)
    assert subscription.status == "past_due"
    # 만료된 카드를 영원히 재시도하지 않는다 — 기간이 지나 이미 lite 로 해석된다.
    assert subscription.next_billing_at is None
    assert subscription_service.get_user_plan(db, user.id).code == "lite"


def test_renew_batch_skips_canceled_subscription(db, toss):
    user = _make_due_subscription(db, "8300000055")
    billing_service.cancel_billing(db, user.id)
    charge_count = len(toss.charge_calls)

    billing_service.charge_due_subscriptions(db)

    # 해지 예약된 구독은 청구 대상이 아니다.
    assert len(toss.charge_calls) == charge_count


def test_renew_batch_survives_one_failure(db, toss, monkeypatch):
    # 한 건의 실패가 배치를 죽이면 안 된다 — B 의 카드 거절로 C 가 갱신되지 않으면 더 큰 사고다.
    failing = _make_due_subscription(db, "8300000056")
    healthy = _make_due_subscription(db, "8300000057")
    healthy_charge = toss.charge_billing

    def selective_charge(**kwargs):
        if kwargs["customer_key"] == "cus_8300000056":
            raise TossError("카드사에서 결제를 거절했습니다.", code="REJECT_CARD_COMPANY")
        return healthy_charge(**kwargs)

    monkeypatch.setattr(toss_client, "charge_billing", selective_charge)

    result = billing_service.charge_due_subscriptions(db)

    assert result["failed"] >= 1
    assert result["charged"] >= 1
    assert (
        db.scalar(select(UserSubscription.status).where(UserSubscription.user_id == failing.id))
        == "past_due"
    )
    assert (
        db.scalar(select(UserSubscription.status).where(UserSubscription.user_id == healthy.id))
        == "active"
    )


# ---- 7) 달력 인식 1개월 ----

@pytest.mark.parametrize(
    ("base", "expected"),
    [
        # 말일 클램프: 31일 → 다음 달 말일.
        ((2026, 1, 31, 12, 0), (2026, 2, 28, 12, 0)),
        # 윤년.
        ((2028, 1, 31, 12, 0), (2028, 2, 29, 12, 0)),
        ((2026, 3, 31, 12, 0), (2026, 4, 30, 12, 0)),
        # 해를 넘긴다.
        ((2026, 12, 15, 9, 30), (2027, 1, 15, 9, 30)),
        # 평범한 날.
        ((2026, 7, 16, 0, 0), (2026, 8, 16, 0, 0)),
    ],
)
def test_add_one_month_clamps_to_last_day(base, expected):
    result = billing_service.add_one_month(datetime(*base, tzinfo=UTC))

    assert result == datetime(*expected, tzinfo=UTC)
