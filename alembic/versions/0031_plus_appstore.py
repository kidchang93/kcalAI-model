"""plus plan + App Store subscription columns

DATA_MODEL.md 32-2. 유료는 플러스 하나로 판다(App Store 인앱 구독).

- `plans` 에 `plus`(4,900원 표시 · 비전 30/일 · 그룹 한도는 pro 와 같다). `pro`·`premium` 은 지우지 않고
  `is_active=false` 로 숨긴다 — 기존 구독 해석(`get_plan`)은 is_active 를 보지 않으므로 안전하다.
- `user_subscriptions` 에 결제 경로 `provider`(toss|appstore|NULL=무료)와 App Store 거래 식별 컬럼.
  **갱신 배치는 provider='toss' 만 청구한다** — 이 컬럼이 없으면 IAP 구독을 우리가 청구하려다
  빌링키가 없어 past_due 로 떨어뜨린다.
- 기존 행: 토스 결제 흔적(`next_billing_at` 또는 `current_period_end`)이 있으면 `toss`, 아니면 NULL.
  `current_period_end` 까지 보는 이유는 해지(canceled)·재시도 포기(past_due) 토스 구독의 next_billing_at 이
  이미 NULL 이기 때문이다 — 그 행들도 토스 구독이다.

Revision ID: 0031_plus_appstore
Revises: 0030_email_signup
Create Date: 2026-10-06
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0031_plus_appstore"
down_revision = "0030_email_signup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO plans (code, label_ko, price_krw, daily_vision_quota, max_group_members, "
            "max_pets, max_owned_groups, sort_order, is_active) "
            "VALUES ('plus', '플러스', 4900, 30, 5, 5, 3, 4, true) "
            "ON CONFLICT (code) DO NOTHING"
        )
    )
    op.execute(sa.text("UPDATE plans SET is_active = false WHERE code IN ('pro', 'premium')"))

    op.add_column("user_subscriptions", sa.Column("provider", sa.String(length=20), nullable=True))
    op.add_column(
        "user_subscriptions",
        sa.Column("store_original_transaction_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "user_subscriptions", sa.Column("store_product_id", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "user_subscriptions", sa.Column("store_environment", sa.String(length=20), nullable=True)
    )
    op.add_column(
        "user_subscriptions",
        sa.Column("is_trial", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_unique_constraint(
        "user_subscriptions_store_original_transaction_id_key",
        "user_subscriptions",
        ["store_original_transaction_id"],
    )

    # 유료 요금제(pro·premium) 행만 토스다. 청구 예정·기간 종료가 남은 lite 행은 토스 테스트 결제를 해 봤다가
    # 무료로 돌아간 계정이라 무료(NULL)로 둔다 — 토스로 잡으면 이용권 화면에 옛 토스 화면이 뜬다.
    # 그 행의 낡은 next_billing_at 은 갱신 배치가 provider='toss' 만 보므로 청구되지 않는다.
    op.execute(
        sa.text(
            "UPDATE user_subscriptions SET provider = 'toss' "
            "WHERE plan_code IN ('pro', 'premium') "
            "AND (next_billing_at IS NOT NULL OR current_period_end IS NOT NULL)"
        )
    )


def downgrade() -> None:
    op.drop_constraint(
        "user_subscriptions_store_original_transaction_id_key", "user_subscriptions", type_="unique"
    )
    op.drop_column("user_subscriptions", "is_trial")
    op.drop_column("user_subscriptions", "store_environment")
    op.drop_column("user_subscriptions", "store_product_id")
    op.drop_column("user_subscriptions", "store_original_transaction_id")
    op.drop_column("user_subscriptions", "provider")

    op.execute(sa.text("UPDATE plans SET is_active = true WHERE code IN ('pro', 'premium')"))
    # 플러스 구독자가 있으면 FK 때문에 실패한다 — 그 상태에서 내리는 것 자체가 사고라 막히는 편이 맞다.
    op.execute(sa.text("DELETE FROM plans WHERE code = 'plus'"))
