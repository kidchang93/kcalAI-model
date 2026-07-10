"""diet recommendations table

DATA_MODEL.md 11장의 diet_recommendations (v2 4차 구현분):
사용자·날짜·끼니 단위 추천 캐시. 같은 날 재조회는 항상 같은 결과를 주고
LLM 재호출을 막는다. UNIQUE(user_id, rec_date, meal_type).

Revision ID: 0006_diet_recommendations
Revises: 0005_option_reference_tables
Create Date: 2026-07-10
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision = "0006_diet_recommendations"
down_revision = "0005_option_reference_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "diet_recommendations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("rec_date", sa.Date(), nullable=False),
        sa.Column("meal_type", sa.String(length=10), nullable=False),
        sa.Column("items", JSONB(), nullable=False),
        sa.Column("excluded", JSONB(), nullable=False),
        sa.Column("source", sa.String(length=20), server_default=sa.text("'llm'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "rec_date", "meal_type"),
    )
    op.create_index("ix_diet_recommendations_id", "diet_recommendations", ["id"])
    op.create_index("ix_diet_recommendations_user_id", "diet_recommendations", ["user_id"])


def downgrade() -> None:
    op.drop_table("diet_recommendations")
