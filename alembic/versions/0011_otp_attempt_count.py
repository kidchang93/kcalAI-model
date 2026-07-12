"""phone_verification_codes attempt_count

OTP 브루트포스 방어: 검증 실패 횟수를 코드 행에 기록하고,
5회 초과 시 코드를 무효화한다 (services/auth_service.py).

Revision ID: 0011_otp_attempt_count
Revises: 0010_condition_exclude_keywords
Create Date: 2026-07-12
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0011_otp_attempt_count"
down_revision = "0010_condition_exclude_keywords"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "phone_verification_codes",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("phone_verification_codes", "attempt_count")
