"""회원 탈퇴(파기·익명화) 회귀 — DATA_MODEL.md 18장.

이 파일이 존재하는 이유: `users` 를 참조하는 FK 가 늘어났는데 `delete_account` 의 삭제 목록이
갱신되지 않으면, 그 회원은 ForeignKeyViolation → **500 으로 영구히 탈퇴할 수 없다.** 2026-07-16에
실제로 발생했다 — 리비전 0017 이 `payments`·`billing_keys` 를 추가했는데 2026-07-11에 작성된 삭제
연쇄가 그대로였다. 결제를 시도한 적 있는 회원(청구 실패 포함)이 전부 해당됐다.

**카카오 unlink 는 호출하지 않는다** — 외부 API 다. `_no_unlink` 픽스처가 대체한다.

카카오 회원번호는 다른 테스트와 겹치지 않도록 8400000xxx 대역을 쓴다.
"""

import pytest
from sqlalchemy import select, text

from models.auth_model import User
from models.subscription_model import BillingKey, Payment
from services import account_service


@pytest.fixture(autouse=True)
def _no_unlink(monkeypatch):
    """탈퇴는 카카오 unlink 를 부른다(의무). 테스트에서 실제 호출은 하지 않는다."""
    monkeypatch.setattr(account_service, "unlink", lambda kakao_id: None)


def _make_user(db, kakao_id: str) -> User:
    user = User(kakao_id=kakao_id, nickname="탈퇴테스터")
    db.add(user)
    db.commit()
    return user


def _make_payment(db, user_id: int, order_id: str, status: str = "done") -> Payment:
    payment = Payment(
        user_id=user_id,
        order_id=order_id,
        plan_code="pro",
        amount=5000,
        status=status,
        method="카드",
    )
    db.add(payment)
    db.commit()
    return payment


def _make_billing_key(db, user_id: int) -> BillingKey:
    billing = BillingKey(
        user_id=user_id,
        billing_key="bk_test_secret",
        customer_key="cus_test",
        card_company="신한",
        card_number="433012******1234",
        card_type="신용",
    )
    db.add(billing)
    db.commit()
    return billing


# ---- 핵심 회귀: 결제 이력이 있어도 탈퇴할 수 있어야 한다 ----

def test_delete_account_with_payment_history_succeeds(db):
    """결제 원장이 있는 회원의 탈퇴. 이 테스트가 없던 동안 500 이었다."""
    user = _make_user(db, "8400000001")
    _make_payment(db, user.id, "ord_delete_1")

    account_service.delete_account(db, user)

    assert db.scalar(select(User).where(User.id == user.id)) is None


def test_delete_account_with_failed_payment_succeeds(db):
    """청구가 **실패한** 회원도 탈퇴할 수 있어야 한다.

    `_create_ready_payment` 가 청구 **전에** ready 행을 커밋하므로, 카드가 거절당한 사람에게도
    원장 행이 남는다 — 이들까지 탈퇴 불가였다.
    """
    user = _make_user(db, "8400000002")
    _make_payment(db, user.id, "ord_delete_2", status="failed")

    account_service.delete_account(db, user)

    assert db.scalar(select(User).where(User.id == user.id)) is None


def test_delete_account_with_billing_key_succeeds(db):
    user = _make_user(db, "8400000003")
    _make_billing_key(db, user.id)

    account_service.delete_account(db, user)

    assert db.scalar(select(User).where(User.id == user.id)) is None


# ---- 파기 vs 보존: 무엇이 남고 무엇이 사라지는가 ----

def test_delete_account_anonymizes_payments_instead_of_deleting(db):
    """원장은 **남기고** user_id 만 끊는다 — 개인정보는 파기하되 대금결제 기록은 보존한다."""
    user = _make_user(db, "8400000004")
    payment = _make_payment(db, user.id, "ord_delete_4")
    payment_id = payment.id

    account_service.delete_account(db, user)

    survived = db.scalar(select(Payment).where(Payment.id == payment_id))

    assert survived is not None, "결제 원장이 삭제됐다 — 거래 기록 보존 의무를 어긴다"
    assert survived.user_id is None, "개인 식별자가 남아 있다 — 파기되지 않았다"
    # 감사 근거는 그대로여야 한다.
    assert survived.order_id == "ord_delete_4"
    assert survived.amount == 5000
    assert survived.status == "done"


def test_delete_account_destroys_billing_key(db):
    """빌링키는 카드 재청구 자격증명이라 **파기**한다 — 익명화로 남길 대상이 아니다."""
    user = _make_user(db, "8400000005")
    _make_billing_key(db, user.id)
    user_id = user.id

    account_service.delete_account(db, user)

    assert db.scalar(select(BillingKey).where(BillingKey.user_id == user_id)) is None


def test_anonymized_payment_is_not_visible_to_anyone(db):
    """익명화된 원장이 다른 회원에게 노출되지 않는다.

    조회는 user_id 일치로만 하므로 NULL 행은 아무 조건에도 걸리지 않아야 한다.
    """
    from services import payment_service

    user = _make_user(db, "8400000006")
    _make_payment(db, user.id, "ord_delete_6")
    other = _make_user(db, "8400000007")

    account_service.delete_account(db, user)

    assert payment_service.list_payments(db, other.id) == []


# ---- 미래 방어: FK 가 늘어나면 이 테스트가 먼저 깨진다 ----

def test_delete_account_covers_every_user_referencing_table(db):
    """`users` 를 참조하는 **모든** 테이블에 행이 있어도 탈퇴가 성공하는가.

    이 테스트는 FK 목록을 DB 에서 직접 읽어, 삭제 연쇄가 다루지 않는 테이블이 새로 생기면
    알려준다. 여기 이름이 나오면 `delete_account` 에 그 테이블을 추가하거나(파기), payments 처럼
    익명화하도록 결정해야 한다.
    """
    referencing = db.execute(
        text(
            """
            SELECT DISTINCT tc.table_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage ccu
              ON tc.constraint_name = ccu.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND ccu.table_name = 'users'
              AND ccu.column_name = 'id'
            ORDER BY tc.table_name
            """
        )
    ).scalars().all()

    # 삭제 연쇄가 실제로 다루는 테이블 (파기 또는 익명화).
    handled = {
        "auth_sessions",
        "billing_keys",
        "diet_recommendations",
        "exercise_goals",
        "exercise_logs",
        "group_members",
        "groups",
        "meal_logs",
        "payments",
        "pets",
        "user_allergies",
        "user_conditions",
        "user_consents",
        "user_goals",
        "user_health_profiles",
        "user_profiles",
        "user_subscriptions",
        "vision_usage_daily",
        "weight_logs",
    }
    missing = set(referencing) - handled

    assert not missing, (
        f"users 를 참조하는 테이블이 삭제 연쇄에 없다: {sorted(missing)}. "
        "그대로 두면 해당 데이터가 있는 회원은 탈퇴가 500 으로 실패한다 — "
        "services/account_service.py 의 목록에 추가하고 이 집합도 갱신할 것."
    )
