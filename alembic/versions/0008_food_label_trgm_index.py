"""food_label pg_trgm index

DATA_MODEL.md 13장의 유사도 검색 (v3 구현분):
인식 라벨과 식약처 식품명의 표기 차이("계란찜" vs "달걀찜")를
pg_trgm similarity 로 흡수한다. /api/nutrition/estimate 3단계 조회의 근거.

Revision ID: 0008_food_label_trgm_index
Revises: 0007_food_nutrition_mfds_columns
Create Date: 2026-07-10
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0008_food_label_trgm_index"
down_revision = "0007_food_nutrition_mfds_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_food_nutrition_food_label_trgm "
        "ON food_nutrition USING gin (food_label gin_trgm_ops)"
    )


def downgrade() -> None:
    # EXTENSION 은 남긴다 — 다른 객체가 쓰고 있을 수 있고, DROP 은 DB 전역 결정이라
    # 마이그레이션 롤백 범위를 넘는다 (13장).
    op.execute("DROP INDEX ix_food_nutrition_food_label_trgm")
