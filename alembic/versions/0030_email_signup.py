"""이메일 회원가입 — users 에 이메일·비밀번호 해시·로그인 잠금, email_verification_codes

카카오·Apple 계정이 없는 사람도 가입할 수 있게 이메일+비밀번호 가입을 붙인다. 이메일은 6자리
코드로 확인한다(SMTP — 비용 없음). 설계는 `docs/DATA_MODEL.md` 21장 '이메일 가입'.

- `users.email` — 이메일 회원의 로그인 식별자라 UNIQUE. 카카오·Apple 회원은 NULL.
- `users.password_hash` — scrypt 해시. 원문은 남기지 않는다.
- `users.failed_login_count`·`login_locked_until` — 비밀번호 대입 방어.
- `email_verification_codes` — 가입·비밀번호 재설정 코드. 회원이 없을 수 있어 FK 없이 이메일로
  귀속한다(탈퇴 연쇄는 이메일 기준으로 지운다).

기존 회원 행은 email·password_hash 가 NULL 이고 failed_login_count 는 0 이다.

Revision ID: 0030_email_signup
Revises: 0029_apple_sign_in
Create Date: 2026-10-06
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0030_email_signup"
down_revision = "0029_apple_sign_in"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(length=254), nullable=True))
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column(
        "users",
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users", sa.Column("login_locked_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "email_verification_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    )
    op.create_index("ix_email_verification_codes_id", "email_verification_codes", ["id"])
    op.create_index("ix_email_verification_codes_email", "email_verification_codes", ["email"])
    op.create_index(
        "ix_email_verification_codes_created_at", "email_verification_codes", ["created_at"]
    )


def downgrade() -> None:
    op.drop_table("email_verification_codes")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_column("users", "login_locked_until")
    op.drop_column("users", "failed_login_count")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "email")
