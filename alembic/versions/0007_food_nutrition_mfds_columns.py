"""food_nutrition mfds columns

DATA_MODEL.md 12장의 food_nutrition 확장 (v2 5차 구현분):
식약처 음식 DB 임포트를 위해 당류·나트륨·칼륨·인·식품대분류 컬럼을 추가한다.
질병 태그 정렬(low_sugar/low_sodium/low_potassium/low_phosphorus)과
meal_type 대분류 매핑의 근거 컬럼이다. 전부 nullable — 기존 llm 행은 값이 없다.

Revision ID: 0007_food_nutrition_mfds_columns
Revises: 0006_diet_recommendations
Create Date: 2026-07-10
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0007_food_nutrition_mfds_columns"
down_revision = "0006_diet_recommendations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("food_nutrition", sa.Column("sugar_g", sa.Numeric(precision=6, scale=1), nullable=True))
    op.add_column("food_nutrition", sa.Column("sodium_mg", sa.Numeric(precision=8, scale=1), nullable=True))
    op.add_column("food_nutrition", sa.Column("potassium_mg", sa.Numeric(precision=8, scale=1), nullable=True))
    op.add_column("food_nutrition", sa.Column("phosphorus_mg", sa.Numeric(precision=8, scale=1), nullable=True))
    op.add_column("food_nutrition", sa.Column("food_group", sa.String(length=30), nullable=True))
    # 추천 후보 풀 쿼리가 source + food_group 으로 거른다 (DATA_MODEL.md 12장).
    op.create_index("ix_food_nutrition_food_group", "food_nutrition", ["food_group"])


def downgrade() -> None:
    op.drop_index("ix_food_nutrition_food_group", "food_nutrition")
    op.drop_column("food_nutrition", "food_group")
    op.drop_column("food_nutrition", "phosphorus_mg")
    op.drop_column("food_nutrition", "potassium_mg")
    op.drop_column("food_nutrition", "sodium_mg")
    op.drop_column("food_nutrition", "sugar_g")
