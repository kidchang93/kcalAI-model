"""결제 환불 — 운영자가 손으로 실행하는 이행 수단.

## 왜 스크립트인가

약관에 환불 규정을 쓰려면 **이행 수단**이 먼저 있어야 한다(`docs/LEGAL_COMPLIANCE.md` §2).
그런데 지금 관리자 화면이 없고, 사용자 셀프 환불은 열지 않는다 — 청약철회 가능 여부(제공
개시·가분성)에 사람의 판단이 필요하고, 자동화하면 잘못 열었을 때 되돌릴 수 없다.

그래서 최소 형태는 "고객이 문의 → 운영자가 확인 → 이 스크립트 실행 → 원장 반영"이다.
관리자 화면이 생기면 같은 서비스 함수(`billing_service.refund_payment`)를 그대로 부르면 된다.

## 안전장치

- **조회 먼저**: `--payment-id` 없이 실행하면 환불 가능한 결제를 보여주기만 한다.
- **미리보기 필수**: `--yes` 없이는 무엇을 할지 출력하고 멈춘다.
- 실제 취소는 `billing_service.refund_payment` 가 세 겹으로 막는다(원장 상태·금액 상한·멱등키).

⚠️ **실행하면 실제로 돈이 나갑니다.** `TOSS_SECRET_KEY` 가 없으면 서비스가 거부한다.

사용법:
    venv/bin/python scripts/refund_payment.py                          # 환불 가능한 결제 목록
    venv/bin/python scripts/refund_payment.py --payment-id 12 --reason "청약철회"
    venv/bin/python scripts/refund_payment.py --payment-id 12 --reason "일할 환불" --amount 2500 --yes
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from database import engine  # noqa: E402
from models.subscription_model import Payment  # noqa: E402
from services import billing_service  # noqa: E402


def list_refundable(session: Session) -> None:
    rows = session.scalars(
        select(Payment)
        .where(Payment.status == billing_service.PAYMENT_DONE)
        .order_by(Payment.approved_at.desc())
        .limit(30)
    ).all()

    if not rows:
        print("환불 가능한 결제가 없습니다 (status='done').")
        return

    print(f"환불 가능한 결제 {len(rows)}건 (최신순):\n")
    print(f"  {'id':>5}  {'user':>6}  {'plan':<8} {'amount':>8}  approved_at")
    for row in rows:
        approved = row.approved_at.strftime("%Y-%m-%d %H:%M") if row.approved_at else "-"
        print(f"  {row.id:>5}  {str(row.user_id):>6}  {row.plan_code:<8} {row.amount:>8,}  {approved}")

    print("\n환불하려면: --payment-id <id> --reason \"사유\" [--amount 부분금액] --yes")


def preview(session: Session, payment_id: int, reason: str, amount: int | None) -> Payment:
    payment = session.scalar(select(Payment).where(Payment.id == payment_id))

    if payment is None:
        raise SystemExit(f"결제 id={payment_id} 를 찾을 수 없습니다.")

    print("다음 결제를 환불합니다:\n")
    print(f"  결제 id     {payment.id}")
    print(f"  주문번호     {payment.order_id}")
    print(f"  회원 id     {payment.user_id}")
    print(f"  요금제       {payment.plan_code}")
    print(f"  결제 금액     {payment.amount:,} 원")
    print(f"  환불 금액     {(amount or payment.amount):,} 원{' (부분)' if amount else ' (전액)'}")
    print(f"  상태         {payment.status}")
    print(f"  사유         {reason}")
    return payment


def main() -> None:
    parser = argparse.ArgumentParser(description="결제 환불 (실제로 돈이 나갑니다)")
    parser.add_argument("--payment-id", type=int, default=None, help="환불할 결제 id")
    parser.add_argument("--reason", type=str, default=None, help="취소 사유 (토스에 그대로 전달)")
    parser.add_argument("--amount", type=int, default=None, help="부분 환불 금액 (생략 시 전액)")
    parser.add_argument("--yes", action="store_true", help="미리보기 없이 실행")
    args = parser.parse_args()

    with Session(engine) as session:
        if args.payment_id is None:
            list_refundable(session)
            return

        if not args.reason:
            raise SystemExit("--reason 은 필수입니다 (토스 cancelReason 에 그대로 들어갑니다).")

        preview(session, args.payment_id, args.reason, args.amount)

        if not args.yes:
            print("\n실행하려면 --yes 를 붙이세요. (아직 아무것도 취소하지 않았습니다)")
            return

        payment = billing_service.refund_payment(
            session, args.payment_id, args.reason, amount=args.amount
        )
        print(
            f"\n환불 완료: {payment.refunded_amount:,} 원 · "
            f"status={payment.status} · canceled_at={payment.canceled_at}"
        )


if __name__ == "__main__":
    main()
