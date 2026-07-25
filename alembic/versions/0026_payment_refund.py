"""payments 환불 컬럼 — 규정을 쓰려면 이행 기록이 먼저

`docs/LEGAL_COMPLIANCE.md` §2: 서버에 환불 코드 경로가 0개였고, 상점관리자에서 손으로
취소해도 `payments` 원장에 아무 흔적이 남지 않았다. 그 상태로 약관에 환불 규정을 적으면
**지킬 수 없는 약속**이 된다.

전자상거래법은 청약철회 시 3영업일 이내 환급을 요구한다. 그것을 이행했다는 것을 증명하려면
언제·얼마를·왜 돌려줬는지가 남아야 한다.

새 테이블을 만들지 않고 같은 행에 기록한다 — 결제 1건과 그 환불은 하나의 거래이고
`order_id` UNIQUE 가 이미 그 단위를 잡고 있다. 부분 환불이면 `amount`(받은 금액)는 그대로
두고 `refunded_amount` 만 채운다.

Revision ID: 0026_payment_refund
Revises: 0025_meal_item_nutrients
Create Date: 2026-07-25
"""

import sqlalchemy as sa

from alembic import op

revision = "0026_payment_refund"
down_revision = "0025_meal_item_nutrients"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("canceled_at", sa.DateTime(timezone=True)),
    ("refunded_amount", sa.Integer()),
    ("refund_reason", sa.String(200)),
)


def upgrade() -> None:
    for name, column_type in _COLUMNS:
        op.add_column("payments", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    for name, _type in _COLUMNS:
        op.drop_column("payments", name)
