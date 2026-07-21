"""group_challenges — 그룹 운동 챌린지

"이번 주 가족 다 같이 150분" 같은 기간제 목표다. 개인 목표(exercise_goals)와 달리 **그룹에 속하고**,
순위가 다른 사람에게 보인다.

⚠️ 순위는 **다른 사람에게 내 건강 데이터를 보이는 것**이라 기존 sensitive_health 동의가 커버하지 않는다.
그래서 `group_activity_share` 동의를 신설했고(services/consent_service.py), 순위에는 **그 동의를 한
멤버만** 나타난다. 참여자 테이블을 따로 두지 않는 이유가 이것이다 — 동의가 곧 참여 의사다.

챌린지는 exercise_logs 를 **집계만** 한다. 기록이 챌린지를 모르게 두어(외래키 없음) 챌린지가 삭제돼도
기록은 그대로다 (docs/ACTIVITY_GUIDANCE.md 3-4).

Revision ID: 0022_group_challenges
Revises: 0021_exercise_goals
Create Date: 2026-07-21
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0022_group_challenges"
down_revision = "0021_exercise_goals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "group_challenges",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        # 만든 사람. 탈퇴해도 챌린지가 남아야 해서 nullable 로 두고 삭제 시 NULL 로 끊는다.
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=60), nullable=False),
        # 중강도 환산 분 기준의 1인 목표. 고강도는 2배로 환산해 비교한다.
        sa.Column("target_minutes", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_group_challenges_id"), "group_challenges", ["id"])
    op.create_index(op.f("ix_group_challenges_group_id"), "group_challenges", ["group_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_group_challenges_group_id"), table_name="group_challenges")
    op.drop_index(op.f("ix_group_challenges_id"), table_name="group_challenges")
    op.drop_table("group_challenges")
