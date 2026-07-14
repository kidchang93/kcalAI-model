"""subscription plans + per-user plan + daily vision quota

DATA_MODEL.md 20장. plans(참조 테이블) · user_subscriptions(회원 1:1) ·
vision_usage_daily(비전 LLM 일일 카운터)를 만들고 시드한다.

기존 회원은 전원 무료 플랜(lite)으로 백필한다 — 구독 행이 없는 회원이 남으면 한도 판정이
갈린다. (조회 경로에도 자기치유가 있지만, 마이그레이션에서 확정해 두는 편이 안전하다.)

Revision ID: 0014_subscription_plans
Revises: 0013_encrypt_health_fields
Create Date: 2026-07-14
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0014_subscription_plans"
down_revision = "0013_encrypt_health_fields"
branch_labels = None
depends_on = None

DEFAULT_PLAN_CODE = "lite"

# 시드 (DATA_MODEL.md 20장 표 그대로).
# max_group_members 는 **본인(owner) 제외** 추가 인원이다. 정원 = 이 값 + 1.
PLAN_SEED = [
    {
        "code": "lite",
        "label_ko": "Lite",
        "price_krw": 0,
        "daily_vision_quota": 3,
        "max_group_members": 1,
        "max_pets": 1,
        "max_owned_groups": 1,
        "sort_order": 1,
        "is_active": True,
    },
    {
        "code": "pro",
        "label_ko": "Pro",
        "price_krw": 5000,
        "daily_vision_quota": 30,
        "max_group_members": 5,
        "max_pets": 5,
        "max_owned_groups": 3,
        "sort_order": 2,
        "is_active": True,
    },
    {
        "code": "premium",
        "label_ko": "Premium",
        "price_krw": 10000,
        "daily_vision_quota": 100,
        "max_group_members": 10,
        "max_pets": 10,
        "max_owned_groups": 5,
        "sort_order": 3,
        "is_active": True,
    },
]


def upgrade() -> None:
    plans = op.create_table(
        "plans",
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("label_ko", sa.String(length=30), nullable=False),
        # 0 = 무료(lite). 결제 연동 전까지 표시용이다.
        sa.Column("price_krw", sa.Integer(), nullable=False),
        sa.Column("daily_vision_quota", sa.Integer(), nullable=False),
        # 본인 제외, 그룹에 추가 가능한 인원.
        sa.Column("max_group_members", sa.Integer(), nullable=False),
        sa.Column("max_pets", sa.Integer(), nullable=False),
        # 그룹을 여러 개 만들어 인원 한도를 우회하는 것을 막는다.
        sa.Column("max_owned_groups", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    op.bulk_insert(plans, PLAN_SEED)

    # user_id 가 PK — 회원 1 : 요금제 1 을 스키마로 강제한다.
    op.create_table(
        "user_subscriptions",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("plan_code", sa.String(length=20), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["plan_code"], ["plans.code"]),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(
        op.f("ix_user_subscriptions_plan_code"), "user_subscriptions", ["plan_code"], unique=False
    )

    # (user_id, usage_date) 복합 PK — 한도 판정과 증가를 한 문장의 UPSERT 로 원자화하기 위한
    # 충돌 대상이다. usage_date 는 KST 기준 날짜다.
    op.create_table(
        "vision_usage_daily",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("used_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "usage_date"),
    )

    # 기존 회원 백필 — 전원 무료 플랜.
    op.execute(
        sa.text(
            "INSERT INTO user_subscriptions (user_id, plan_code) "
            "SELECT id, :plan FROM users"
        ).bindparams(plan=DEFAULT_PLAN_CODE)
    )


def downgrade() -> None:
    op.drop_table("vision_usage_daily")
    op.drop_index(op.f("ix_user_subscriptions_plan_code"), table_name="user_subscriptions")
    op.drop_table("user_subscriptions")
    op.drop_table("plans")
