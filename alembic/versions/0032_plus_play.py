"""Google Play subscription purchase token

DATA_MODEL.md 33-2. 플러스를 Google Play 구독으로도 판다.

- `user_subscriptions.store_purchase_token` (TEXT, UNIQUE, NULL 허용) — Google 구매 토큰. 한 토큰은 한 회원에게만
  붙는다. Apple 거래 ID(`store_original_transaction_id`, 64자)와 길이·모양이 달라 컬럼을 나눈다.
- `provider` 에 `play` 가 온다(컬럼은 String(20) 그대로). 갱신 배치는 `provider='toss'` 만 청구하므로 손대지 않는다.

Revision ID: 0032_plus_play
Revises: 0031_plus_appstore
Create Date: 2026-10-14
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0032_plus_play"
down_revision = "0031_plus_appstore"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_subscriptions", sa.Column("store_purchase_token", sa.Text(), nullable=True))
    op.create_unique_constraint(
        "user_subscriptions_store_purchase_token_key", "user_subscriptions", ["store_purchase_token"]
    )


def downgrade() -> None:
    op.drop_constraint("user_subscriptions_store_purchase_token_key", "user_subscriptions", type_="unique")
    op.drop_column("user_subscriptions", "store_purchase_token")
