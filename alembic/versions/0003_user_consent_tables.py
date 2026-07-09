"""user consent + sensitive health tables

DATA_MODEL.md 6장 상위 4개 테이블 (v2 1차 구현분):
user_consents, user_health_profiles, user_conditions, user_allergies.
그룹·반려동물·추천은 다음 차수다.

Revision ID: 0003_user_consent_tables
Revises: 0002_health_tables
Create Date: 2026-07-09
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_user_consent_tables"
down_revision = "0002_health_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_consents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("agreed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_consents_id", "user_consents", ["id"])
    op.create_index("ix_user_consents_user_id", "user_consents", ["user_id"])

    op.create_table(
        "user_health_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("blood_type", sa.String(length=10), nullable=True),
        sa.Column("rh", sa.String(length=1), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_user_health_profiles_id", "user_health_profiles", ["id"])

    op.create_table(
        "user_conditions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("condition", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "condition"),
    )
    op.create_index("ix_user_conditions_id", "user_conditions", ["id"])
    op.create_index("ix_user_conditions_user_id", "user_conditions", ["user_id"])

    op.create_table(
        "user_allergies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("allergen", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "allergen"),
    )
    op.create_index("ix_user_allergies_id", "user_allergies", ["id"])
    op.create_index("ix_user_allergies_user_id", "user_allergies", ["user_id"])


def downgrade() -> None:
    op.drop_table("user_allergies")
    op.drop_table("user_conditions")
    op.drop_table("user_health_profiles")
    op.drop_table("user_consents")
