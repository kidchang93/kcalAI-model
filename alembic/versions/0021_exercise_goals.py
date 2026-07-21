"""exercise_goals — 개인 주간 운동 목표

기록(exercise_logs)과 **분리**한다. 목표가 바뀌어도 기록은 불변이어야 하고, 기록은 목표를
모르는 채로 쌓여야 한다 (docs/ACTIVITY_GUIDANCE.md 3-4).

user_goals(식단 목표)와 같은 이력 구조를 쓴다 — 열린 목표는 ended_at IS NULL 하나뿐이고,
변경하면 이전 행을 닫는다. 목표를 낮췄는지 높였는지가 남아야 나중에 조언의 근거가 된다.

목표를 설정하지 않은 사용자는 행이 없다. 그때는 **지침 권장량(주 150분·근력 2일)이 기본값**이며,
목표는 그 값을 덮어쓰는 것이다 — 목표가 없다고 요약이 동작하지 않으면 안 된다.

Revision ID: 0021_exercise_goals
Revises: 0020_exercise_logs
Create Date: 2026-07-21
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0021_exercise_goals"
down_revision = "0020_exercise_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exercise_goals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        # 주당 목표 활동량(중강도 환산 분). 고강도는 2배로 환산해 이 값과 비교한다.
        sa.Column("weekly_minutes", sa.Integer(), nullable=False),
        sa.Column("weekly_strength_days", sa.Integer(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_exercise_goals_id"), "exercise_goals", ["id"])
    op.create_index(op.f("ix_exercise_goals_user_id"), "exercise_goals", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_exercise_goals_user_id"), table_name="exercise_goals")
    op.drop_index(op.f("ix_exercise_goals_id"), table_name="exercise_goals")
    op.drop_table("exercise_goals")
