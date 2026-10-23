"""store transaction ledger

DATA_MODEL.md 35장. `user_subscriptions` 는 회원당 한 행을 덮어써 현재 상태만 남기므로, 스토어 결제 1건마다
1행을 남기는 원장을 따로 둔다 — App Store 거래(transactionId)·Google Play 주문(orderId).

- `(provider, transaction_id)` UNIQUE — 같은 거래를 몇 번 다시 받아도 한 행이다(환불 등 상태만 갱신).
- 탈퇴하면 소프트 딜리트 — `deleted_at` 을 찍고 `user_id` 를 끊는다. 결제일로부터 5년 뒤 정리 배치가 물리 삭제한다.

Revision ID: 0033_store_transactions
Revises: 0032_plus_play
Create Date: 2026-10-23
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0033_store_transactions"
down_revision = "0032_plus_play"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "store_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("transaction_id", sa.String(100), nullable=False),
        sa.Column("product_id", sa.String(100), nullable=True),
        sa.Column("environment", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("amount", sa.Numeric(14, 3), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("provider", "transaction_id", name="store_transactions_provider_transaction_id_key"),
    )
    op.create_index("ix_store_transactions_user_id", "store_transactions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_store_transactions_user_id", table_name="store_transactions")
    op.drop_table("store_transactions")
