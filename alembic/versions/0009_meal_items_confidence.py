"""meal_items confidence precision

DATA_MODEL.md 3장의 meal_items.confidence 정밀도 수정:
Numeric(4,3)은 소수 3자리 반올림이라 YOLO score 0.9995 이상이 전부 1.0으로
저장돼 '모델 개선 근거' 데이터가 왜곡된다 (e2e 실측: 0.9998 → 1.0).
Numeric(5,4)로 넓혀 소수 4자리를 보존한다.

Revision ID: 0009_meal_items_confidence
Revises: 0008_food_label_trgm_index
Create Date: 2026-07-11
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0009_meal_items_confidence"
down_revision = "0008_food_label_trgm_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "meal_items",
        "confidence",
        type_=sa.Numeric(precision=5, scale=4),
        existing_type=sa.Numeric(precision=4, scale=3),
        existing_nullable=True,
    )


def downgrade() -> None:
    # 소수 4자리 값은 3자리로 반올림된다 (정밀도 손실 감수).
    op.alter_column(
        "meal_items",
        "confidence",
        type_=sa.Numeric(precision=4, scale=3),
        existing_type=sa.Numeric(precision=5, scale=4),
        existing_nullable=True,
    )
