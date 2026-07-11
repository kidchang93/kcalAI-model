"""condition_types exclude_keywords

DATA_MODEL.md 16장의 기록 시 경고 판정용 컬럼:
condition_types 에는 dietary_tags(정렬용)만 있어 문자열 키워드 판정이
불가능했다. exclude_keywords JSONB 를 추가하고 시드를 넣는다.
시드는 전문가 감수 전까지의 잠정 사전이다. 추천 엔진은 이 컬럼을
읽지 않는다 — 추천 동작 불변 (16장).

Revision ID: 0010_condition_exclude_keywords
Revises: 0009_meal_items_confidence
Create Date: 2026-07-11
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision = "0010_condition_exclude_keywords"
down_revision = "0009_meal_items_confidence"
branch_labels = None
depends_on = None

# 시드 (DATA_MODEL.md 16장 표 그대로)
CONDITION_KEYWORDS = {
    "diabetes": ["설탕", "시럽", "꿀", "사탕", "초콜릿", "케이크"],
    "pregnancy": ["소주", "맥주", "와인", "막걸리", "육회", "생선회"],
    "ckd": ["젓갈", "장아찌", "라면"],
    "cancer": ["육회", "생선회"],
    "hypertension": ["젓갈", "장아찌", "라면"],
}


def upgrade() -> None:
    op.add_column("condition_types", sa.Column("exclude_keywords", JSONB(), nullable=True))

    condition_types = sa.table(
        "condition_types",
        sa.column("code", sa.String),
        sa.column("exclude_keywords", JSONB),
    )
    for code, keywords in CONDITION_KEYWORDS.items():
        op.execute(
            condition_types.update()
            .where(condition_types.c.code == code)
            .values(exclude_keywords=keywords)
        )
    # 시드에 없는 코드(향후 추가분 포함)는 빈 배열로 채워 NOT NULL 을 보장한다.
    op.execute(
        condition_types.update()
        .where(condition_types.c.exclude_keywords.is_(None))
        .values(exclude_keywords=sa.text("'[]'::jsonb"))
    )
    op.alter_column("condition_types", "exclude_keywords", nullable=False)


def downgrade() -> None:
    op.drop_column("condition_types", "exclude_keywords")
