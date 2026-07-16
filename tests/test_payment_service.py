"""결제 내역 조회 (DATA_MODEL.md 23장). 읽기 전용.

카카오 회원번호는 다른 테스트와 겹치지 않도록 820000100x 대역을 쓴다.
"""

from datetime import UTC, datetime, timedelta

import pytest

from models.auth_model import User
from models.subscription_model import Payment
from services import payment_service


def _make_user(db, kakao_id: str) -> User:
    user = User(kakao_id=kakao_id, nickname="테스터")
    db.add(user)
    db.commit()
    return user


def _add_payment(db, user_id: int, order_id: str, **kwargs) -> Payment:
    created_at = kwargs.pop("created_at", None)
    payment = Payment(
        user_id=user_id,
        order_id=order_id,
        plan_code=kwargs.pop("plan_code", "pro"),
        amount=kwargs.pop("amount", 5000),
        status=kwargs.pop("status", "done"),
        method=kwargs.pop("method", "카드"),
        approved_at=kwargs.pop("approved_at", None),
        fail_reason=kwargs.pop("fail_reason", None),
    )
    # server_default(func.now())는 트랜잭션 시작 시각으로 고정돼 같은 트랜잭션 내 행이 전부 동률이
    # 된다. 최신순 정렬을 검증하려면 created_at 을 명시적으로 벌려야 한다.
    if created_at is not None:
        payment.created_at = created_at
    db.add(payment)
    db.commit()
    return payment


def test_list_payments_newest_first(db):
    user = _make_user(db, "8200001000")
    now = datetime.now(UTC)
    _add_payment(db, user.id, "ord_old", created_at=now - timedelta(hours=2))
    _add_payment(db, user.id, "ord_new", created_at=now)
    _add_payment(db, user.id, "ord_mid", created_at=now - timedelta(hours=1))

    items = payment_service.list_payments_view(db, user.id)["payments"]

    assert [item["order_id"] for item in items] == ["ord_new", "ord_mid", "ord_old"]


def test_list_payments_only_returns_mine(db):
    me = _make_user(db, "8200001001")
    other = _make_user(db, "8200001002")
    _add_payment(db, me.id, "ord_mine")
    _add_payment(db, other.id, "ord_theirs")

    items = payment_service.list_payments_view(db, me.id)["payments"]

    assert [item["order_id"] for item in items] == ["ord_mine"]


def test_list_payments_empty_is_empty_list(db):
    user = _make_user(db, "8200001003")

    assert payment_service.list_payments_view(db, user.id)["payments"] == []


def test_plan_label_comes_from_plans(db):
    user = _make_user(db, "8200001004")
    _add_payment(db, user.id, "ord_pro", plan_code="pro")

    item = payment_service.list_payments_view(db, user.id)["payments"][0]

    # conftest 가 plans 에 pro → 'Pro' 를 시드한다.
    assert item["plan_code"] == "pro"
    assert item["plan_label"] == "Pro"


def test_plan_label_falls_back_to_code_when_plan_missing(db):
    # payments.plan_code 는 plans FK 라 실제로는 없는 코드로 결제행을 만들 수 없다. 폴백은
    # 방어 코드이므로 헬퍼를 직접 검증한다.
    assert payment_service._plan_label(db, "no_such_plan") == "no_such_plan"


def test_get_payment_returns_own(db):
    user = _make_user(db, "8200001005")
    created = _add_payment(db, user.id, "ord_get", amount=10000, status="done")

    item = payment_service.get_payment_view(db, user.id, created.id)

    assert item["id"] == created.id
    assert item["amount"] == 10000
    assert item["status"] == "done"


def test_get_others_payment_is_404(db):
    me = _make_user(db, "8200001006")
    other = _make_user(db, "8200001007")
    theirs = _add_payment(db, other.id, "ord_hidden")

    # 남의 것은 존재 자체를 숨긴다 (LookupError → api 가 404 로 변환).
    with pytest.raises(LookupError):
        payment_service.get_payment_view(db, me.id, theirs.id)


def test_get_missing_payment_is_404(db):
    user = _make_user(db, "8200001008")

    with pytest.raises(LookupError):
        payment_service.get_payment_view(db, user.id, 999999999)
