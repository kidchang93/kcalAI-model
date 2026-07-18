"""food_nutrition.serving_size_g — 1인분이 몇 g 인지의 환산 계수

앱이 사용자가 먹은 g 을 자유 입력하면 kcal 을 재계산할 수 있도록, estimate 응답에 실어 줄
환산 계수다. 의미: 이 음식 1인분(= serving_desc 가 가리키는 1회 제공량)이 몇 g 인가.
앱은 serving_ratio = 사용자입력g ÷ serving_size_g 로 환산한다. **ml 은 밀도≈1 로 g 과 동일
수치 취급**(국·죽·면 국물류). 원물 등 1회 제공량이 미상이면 NULL → 앱이 인분 모드로 폴백한다.

nullable — 기존 행은 값이 없다. 임포트 스크립트(import_mfds_food·correct_common_foods·
seed_curated_foods)가 식품중량/serving_desc 에서 g 을 채워 재적재한다 (DATA_MODEL.md 12·14장).

revision id 는 alembic_version.version_num(varchar(32)) 한도에 맞춰 짧게 둔다
(전체 이름 '0019_food_nutrition_serving_size_g' 는 34자로 초과한다).

Revision ID: 0019_food_serving_size_g
Revises: 0018_payments_user_nullable
Create Date: 2026-07-18
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0019_food_serving_size_g"
down_revision = "0018_payments_user_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "food_nutrition",
        sa.Column("serving_size_g", sa.Numeric(precision=6, scale=1), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("food_nutrition", "serving_size_g")
