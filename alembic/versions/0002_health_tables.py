"""health domain tables

DATA_MODEL.md 3장의 6개 테이블:
user_profiles, user_goals, meal_logs, meal_items, weight_logs, food_nutrition.

Revision ID: 0002_health_tables
Revises: 0001_initial_auth
Create Date: 2026-07-09
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_health_tables"
down_revision = "0001_initial_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("sex", sa.String(length=10), nullable=False),
        sa.Column("birth_year", sa.Integer(), nullable=False),
        sa.Column("height_cm", sa.Numeric(precision=5, scale=1), nullable=False),
        sa.Column("weight_kg", sa.Numeric(precision=5, scale=1), nullable=False),
        sa.Column("activity_level", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_user_profiles_id", "user_profiles", ["id"])

    op.create_table(
        "user_goals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("goal_type", sa.String(length=10), nullable=False),
        sa.Column("target_kcal", sa.Integer(), nullable=False),
        sa.Column("target_weight_kg", sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_goals_id", "user_goals", ["id"])
    op.create_index("ix_user_goals_user_id", "user_goals", ["user_id"])

    op.create_table(
        "meal_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("logged_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("meal_type", sa.String(length=10), nullable=False),
        sa.Column("photo_s3_key", sa.String(length=255), nullable=True),
        sa.Column("total_kcal", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_meal_logs_id", "meal_logs", ["id"])
    op.create_index("ix_meal_logs_user_id", "meal_logs", ["user_id"])
    op.create_index("ix_meal_logs_logged_at", "meal_logs", ["logged_at"])

    op.create_table(
        "meal_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meal_log_id", sa.Integer(), nullable=False),
        sa.Column("food_label", sa.String(length=100), nullable=False),
        sa.Column("serving_ratio", sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column("kcal", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["meal_log_id"], ["meal_logs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_meal_items_id", "meal_items", ["id"])
    op.create_index("ix_meal_items_meal_log_id", "meal_items", ["meal_log_id"])

    op.create_table(
        "weight_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("weight_kg", sa.Numeric(precision=5, scale=1), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_weight_logs_id", "weight_logs", ["id"])
    op.create_index("ix_weight_logs_user_id", "weight_logs", ["user_id"])
    op.create_index("ix_weight_logs_measured_at", "weight_logs", ["measured_at"])

    op.create_table(
        "food_nutrition",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("food_label", sa.String(length=100), nullable=False),
        sa.Column("kcal_per_serving", sa.Integer(), nullable=False),
        sa.Column("serving_desc", sa.String(length=100), nullable=False),
        sa.Column("carbs_g", sa.Numeric(precision=6, scale=1), nullable=True),
        sa.Column("protein_g", sa.Numeric(precision=6, scale=1), nullable=True),
        sa.Column("fat_g", sa.Numeric(precision=6, scale=1), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_food_nutrition_id", "food_nutrition", ["id"])
    op.create_index("ix_food_nutrition_food_label", "food_nutrition", ["food_label"], unique=True)


def downgrade() -> None:
    op.drop_table("food_nutrition")
    op.drop_table("weight_logs")
    op.drop_table("meal_items")
    op.drop_table("meal_logs")
    op.drop_table("user_goals")
    op.drop_table("user_profiles")
