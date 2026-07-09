"""group + pet tables

DATA_MODEL.md 6장의 그룹·반려동물 5개 테이블 (v2 2차 구현분):
groups, group_members, pets, group_pets, pet_feeding_logs.
연동·추천(health_integrations 이하)은 다음 차수다.

Revision ID: 0004_group_pet_tables
Revises: 0003_user_consent_tables
Create Date: 2026-07-09
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_group_pet_tables"
down_revision = "0003_user_consent_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("invite_code", sa.String(length=12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_groups_id", "groups", ["id"])
    op.create_index("ix_groups_owner_id", "groups", ["owner_id"])
    op.create_index("ix_groups_invite_code", "groups", ["invite_code"], unique=True)

    op.create_table(
        "group_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "user_id"),
    )
    op.create_index("ix_group_members_id", "group_members", ["id"])
    op.create_index("ix_group_members_group_id", "group_members", ["group_id"])
    op.create_index("ix_group_members_user_id", "group_members", ["user_id"])

    op.create_table(
        "pets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("species", sa.String(length=10), nullable=False),
        sa.Column("breed", sa.String(length=50), nullable=True),
        sa.Column("birth_year", sa.Integer(), nullable=True),
        sa.Column("weight_kg", sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column("is_neutered", sa.Boolean(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pets_id", "pets", ["id"])
    op.create_index("ix_pets_owner_id", "pets", ["owner_id"])

    op.create_table(
        "group_pets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("pet_id", sa.Integer(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.ForeignKeyConstraint(["pet_id"], ["pets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "pet_id"),
    )
    op.create_index("ix_group_pets_id", "group_pets", ["id"])
    op.create_index("ix_group_pets_group_id", "group_pets", ["group_id"])
    op.create_index("ix_group_pets_pet_id", "group_pets", ["pet_id"])

    op.create_table(
        "pet_feeding_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pet_id", sa.Integer(), nullable=False),
        sa.Column("fed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("food_label", sa.String(length=100), nullable=False),
        sa.Column("amount_g", sa.Numeric(precision=6, scale=1), nullable=False),
        sa.Column("kcal", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["pet_id"], ["pets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pet_feeding_logs_id", "pet_feeding_logs", ["id"])
    op.create_index("ix_pet_feeding_logs_pet_id", "pet_feeding_logs", ["pet_id"])
    op.create_index("ix_pet_feeding_logs_fed_at", "pet_feeding_logs", ["fed_at"])


def downgrade() -> None:
    op.drop_table("pet_feeding_logs")
    op.drop_table("group_pets")
    op.drop_table("pets")
    op.drop_table("group_members")
    op.drop_table("groups")
