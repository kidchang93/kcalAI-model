"""kakao login replaces phone/SMS auth

DATA_MODEL.md 21장. 인증 수단을 휴대폰 OTP(SMS) → 카카오 로그인으로 교체한다.

- `users.kakao_id`(유니크) · `users.nickname` 추가. kakao_id 가 새 로그인 식별자다.
- `users.phone_number` 를 nullable 로 완화하고 유니크를 푼다. **컬럼은 남긴다** — 비즈 앱 전환
  후 전화번호 동의항목을 받게 되면 다시 채울 자리이고, 기존 행의 값을 지우지 않기 위해서다.
- `phone_verification_codes` → `kakao_link_codes` 로 교체 (OTP 코드는 더 이상 발급하지 않는다).

**기존 회원은 지우지 않는다.** kakao_id 가 NULL 이라 로그인만 불가능해진다 — 데이터를 남긴 채
사용자가 판단할 수 있게 한다. (정리하려면: DELETE FROM users WHERE kakao_id IS NULL; 단 자식
행을 먼저 지워야 한다 — account_service.delete_account 의 순서를 참고.)

Revision ID: 0015_kakao_login
Revises: 0014_subscription_plans
Create Date: 2026-07-14
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0015_kakao_login"
down_revision = "0014_subscription_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("kakao_id", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("nickname", sa.String(length=50), nullable=True))
    op.create_index(op.f("ix_users_kakao_id"), "users", ["kakao_id"], unique=True)

    # 휴대폰 번호는 더 이상 식별자가 아니다 — NOT NULL·UNIQUE 를 푼다 (값은 보존).
    op.alter_column("users", "phone_number", existing_type=sa.String(length=20), nullable=True)
    op.drop_index("ix_users_phone_number", table_name="users")
    op.create_index(op.f("ix_users_phone_number"), "users", ["phone_number"], unique=False)

    # is_phone_verified 는 이제 기본 False (SMS 인증을 하지 않는다).
    op.alter_column(
        "users", "is_phone_verified", existing_type=sa.Boolean(), server_default=sa.text("false")
    )

    op.create_table(
        "kakao_link_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        # 세션 토큰과 같은 규칙으로 해시만 저장한다 (딥링크 URL 에 원문이 실려 나가므로).
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("kakao_id", sa.String(length=32), nullable=False),
        sa.Column("nickname", sa.String(length=50), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_kakao_link_codes_id"), "kakao_link_codes", ["id"], unique=False)
    op.create_index(
        op.f("ix_kakao_link_codes_code_hash"), "kakao_link_codes", ["code_hash"], unique=True
    )
    op.create_index(
        op.f("ix_kakao_link_codes_kakao_id"), "kakao_link_codes", ["kakao_id"], unique=False
    )

    op.drop_table("phone_verification_codes")

    # 휴대폰 인증으로 발급된 세션은 전부 폐기한다. 인증 수단 자체가 바뀌었는데 옛 토큰이 살아
    # 있으면, 카카오로 로그인한 적 없는 사람이 legacy 계정으로 계속 접속한다 (실제로 그랬다 —
    # 로그인도 안 했는데 /api/me/profile 이 200을 냈다). 세션 TTL 이 30일이라 저절로 만료되길
    # 기다릴 수도 없다.
    op.execute("DELETE FROM auth_sessions")


def downgrade() -> None:
    # 되돌리면 SMS 인증으로 복귀한다. phone_number 를 NOT NULL·UNIQUE 로 되돌리려면 값이 모두
    # 채워져 있어야 하므로, 카카오로 가입한 회원이 있으면 실패한다 (의도된 안전장치).
    op.create_table(
        "phone_verification_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("phone_number", sa.String(length=20), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_phone_verification_codes_id"), "phone_verification_codes", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_phone_verification_codes_phone_number"),
        "phone_verification_codes",
        ["phone_number"],
        unique=False,
    )
    op.create_index(
        op.f("ix_phone_verification_codes_purpose"),
        "phone_verification_codes",
        ["purpose"],
        unique=False,
    )

    op.drop_index(op.f("ix_kakao_link_codes_kakao_id"), table_name="kakao_link_codes")
    op.drop_index(op.f("ix_kakao_link_codes_code_hash"), table_name="kakao_link_codes")
    op.drop_index(op.f("ix_kakao_link_codes_id"), table_name="kakao_link_codes")
    op.drop_table("kakao_link_codes")

    op.alter_column(
        "users", "is_phone_verified", existing_type=sa.Boolean(), server_default=sa.text("true")
    )
    op.drop_index(op.f("ix_users_phone_number"), table_name="users")
    op.create_index("ix_users_phone_number", "users", ["phone_number"], unique=True)
    op.alter_column("users", "phone_number", existing_type=sa.String(length=20), nullable=False)

    op.drop_index(op.f("ix_users_kakao_id"), table_name="users")
    op.drop_column("users", "nickname")
    op.drop_column("users", "kakao_id")
