"""payments + billing_keys 테이블, user_subscriptions 자동결제 컬럼

토스페이먼츠 자동결제(빌링) 연동을 위한 스키마.
- billing_keys: 회원당 1개 결제수단(빌링키). billing_key 는 카드를 청구할 수 있는 민감정보라
  앱 레이어에서 암호문으로 저장한다(models 의 EncryptedString → DB 에는 VARCHAR).
- payments: 최초/갱신 청구 1건마다 1행(원장). order_id UNIQUE 로 중복 반영 방지.
- user_subscriptions: 자동결제 상태(status·현재기간종료·다음청구·자동갱신해지) 컬럼 추가.
  기존 행은 status='active', 기간·청구 null(무료/무기한과 동일하게 동작).

Revision ID: 0017_payments_billing
Revises: 0016_lite_vision_quota_5
Create Date: 2026-07-16
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0017_payments_billing"
down_revision = "0016_lite_vision_quota_5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billing_keys",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        # 토스 billingKey(암호문 저장). 앱 레이어에서 복호화한다.
        sa.Column("billing_key", sa.String(length=512), nullable=False),
        sa.Column("customer_key", sa.String(length=64), nullable=False),
        sa.Column("card_company", sa.String(length=30), nullable=True),
        sa.Column("card_number", sa.String(length=30), nullable=True),
        sa.Column("card_type", sa.String(length=20), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("order_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("plan_code", sa.String(length=20), sa.ForeignKey("plans.code"), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("payment_key", sa.String(length=200), nullable=True),
        sa.Column("method", sa.String(length=30), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fail_code", sa.String(length=50), nullable=True),
        sa.Column("fail_reason", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_payments_user_id", "payments", ["user_id"])

    op.add_column(
        "user_subscriptions",
        sa.Column(
            "status", sa.String(length=20), server_default=sa.text("'active'"), nullable=False
        ),
    )
    op.add_column(
        "user_subscriptions",
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_subscriptions",
        sa.Column("next_billing_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_subscriptions",
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("user_subscriptions", "cancel_at_period_end")
    op.drop_column("user_subscriptions", "next_billing_at")
    op.drop_column("user_subscriptions", "current_period_end")
    op.drop_column("user_subscriptions", "status")
    op.drop_index("ix_payments_user_id", table_name="payments")
    op.drop_table("payments")
    op.drop_table("billing_keys")
