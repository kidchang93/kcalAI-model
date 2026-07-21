"""exercise_logs — 날마다 쌓이는 운동 기록

식단(meal_logs)과 같은 성격의 기록이다. 하루 여러 건, soft delete, 하루 경계는 UTC 자정 —
끼니 기록의 관례를 그대로 따라 두 도메인이 같은 방식으로 동작하게 한다 (docs/ACTIVITY_GUIDANCE.md 3-2).

`source` 는 처음부터 둔다. 지금은 전부 'manual'(사용자 직접 입력)이지만, 3단계에서 Apple 건강·
Health Connect 가 같은 테이블에 'healthkit'/'health_connect' 로 들어오게 해서 그때 스키마를 바꾸지 않는다.
앱과 웹이 같은 레벨의 서비스여야 하므로 기록·조회 API 는 플랫폼 중립이고, 연동은 입력 경로가 하나 느는 것뿐이다.

`intensity` 는 보건복지부 지침의 강도 축(light/moderate/vigorous)과 일치시킨다 — 주간 집계에서
"중강도 150~300분" 권장과 바로 대조하기 위해서다.

Revision ID: 0020_exercise_logs
Revises: 0019_food_serving_size_g
Create Date: 2026-07-21
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0020_exercise_logs"
down_revision = "0019_food_serving_size_g"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exercise_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exercise_type", sa.String(length=30), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("intensity", sa.String(length=10), nullable=False),
        # 서버가 MET 로 산출하거나 사용자가 직접 준 값. 체중을 모르면 산출할 수 없어 nullable.
        sa.Column("kcal", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("memo", sa.String(length=200), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_exercise_logs_id"), "exercise_logs", ["id"])
    op.create_index(op.f("ix_exercise_logs_user_id"), "exercise_logs", ["user_id"])
    # 날짜별 조회·기간 집계가 주 질의라 (user_id, performed_at) 복합 인덱스를 둔다.
    op.create_index(
        "ix_exercise_logs_user_performed", "exercise_logs", ["user_id", "performed_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_exercise_logs_user_performed", table_name="exercise_logs")
    op.drop_index(op.f("ix_exercise_logs_user_id"), table_name="exercise_logs")
    op.drop_index(op.f("ix_exercise_logs_id"), table_name="exercise_logs")
    op.drop_table("exercise_logs")
