from sqlalchemy import select
from sqlalchemy.orm import Session

from models.subscription_model import Payment, Plan


# ---- 조회 ----

def list_payments(db: Session, user_id: int) -> list[Payment]:
    # 최신순. created_at 이 같은(같은 초에 두 건) 경우를 대비해 id 로 2차 정렬한다.
    return list(
        db.scalars(
            select(Payment)
            .where(Payment.user_id == user_id)
            .order_by(Payment.created_at.desc(), Payment.id.desc())
        ).all()
    )


def get_payment(db: Session, user_id: int, payment_id: int) -> Payment:
    payment = db.scalar(select(Payment).where(Payment.id == payment_id))

    # 없거나 남의 것이면 존재 자체를 숨긴다 (meal_logs·pets 삭제와 같은 존재 은닉 규칙).
    if payment is None or payment.user_id != user_id:
        raise LookupError("결제 내역을 찾을 수 없습니다.")

    return payment


# ---- 응답 조립 (api 레이어는 HTTP 변환만 한다) ----

def _plan_label(db: Session, plan_code: str) -> str:
    # subscription_service.get_plan 과 같은 조회 방식이되, 여기서는 폴백이 필요해 예외를 던지지
    # 않는다 — 요금제가 삭제됐어도 과거 결제 내역은 조회 가능해야 한다.
    label = db.scalar(select(Plan.label_ko).where(Plan.code == plan_code))
    return label if label is not None else plan_code


def payment_view(db: Session, payment: Payment) -> dict:
    return {
        "id": payment.id,
        "order_id": payment.order_id,
        "plan_code": payment.plan_code,
        "plan_label": _plan_label(db, payment.plan_code),
        "amount": payment.amount,
        "status": payment.status,
        "method": payment.method,
        "approved_at": payment.approved_at,
        "fail_reason": payment.fail_reason,
        "created_at": payment.created_at,
    }


def list_payments_view(db: Session, user_id: int) -> dict:
    return {"payments": [payment_view(db, payment) for payment in list_payments(db, user_id)]}


def get_payment_view(db: Session, user_id: int, payment_id: int) -> dict:
    return payment_view(db, get_payment(db, user_id, payment_id))
