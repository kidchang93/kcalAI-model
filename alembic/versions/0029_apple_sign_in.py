"""Sign in with Apple — users 에 apple_sub · apple_refresh_token

App Store 심사 4.8: 소셜 로그인(카카오)만 있으면 동등한 대안 로그인이 필요하다
(`docs/LEGAL_COMPLIANCE.md` §6-6). 그래서 Apple 로그인을 붙인다 — `docs/DATA_MODEL.md` 21장.

- `apple_sub` — identity token 의 `sub`. Apple 회원의 로그인 식별자라 UNIQUE.
- `apple_refresh_token` — 탈퇴 시 Apple 에 폐기(revoke)를 요청하는 데 쓴다. **암호문**으로 저장한다
  (`crypto.EncryptedString`, 키는 HEALTH_ENCRYPTION_KEY). 컬럼 타입은 그냥 VARCHAR 다.

카카오 컬럼·`kakao_link_codes` 는 그대로 둔다. 기존 회원 행은 둘 다 NULL 이다.
탈퇴 연쇄는 바뀌지 않는다 — 새 테이블이 아니라 `users` 행의 컬럼이라 행과 함께 파기된다.

Revision ID: 0029_apple_sign_in
Revises: 0028_care_visits
Create Date: 2026-10-05
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0029_apple_sign_in"
down_revision = "0028_care_visits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("apple_sub", sa.String(length=64), nullable=True))
    op.add_column(
        "users", sa.Column("apple_refresh_token", sa.String(length=1024), nullable=True)
    )
    op.create_index("ix_users_apple_sub", "users", ["apple_sub"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_apple_sub", table_name="users")
    op.drop_column("users", "apple_refresh_token")
    op.drop_column("users", "apple_sub")
