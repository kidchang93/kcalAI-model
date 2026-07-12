"""auth_sessions token sha256 hashing

세션 토큰을 평문 대신 sha256 해시로 저장한다 (DB 유출 시 토큰 재사용 방지).
기존 평문 토큰을 해시로 변환해 발급된 세션을 보존한다 — 앱이 들고 있는
원문 토큰은 이후 조회 시 서버가 해시해 비교하므로 그대로 동작한다.

token_urlsafe(48) 평문(base64url 64자)과 sha256 hex(64자)는 길이가 같아
String(128) 컬럼 변경은 필요 없다.

Revision ID: 0012_hash_session_tokens
Revises: 0011_otp_attempt_count
Create Date: 2026-07-12
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0012_hash_session_tokens"
down_revision = "0011_otp_attempt_count"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL 11+ 내장 sha256(). 이 리비전은 평문 상태에서 정확히 한 번 실행된다.
    op.execute(
        "UPDATE auth_sessions "
        "SET token = encode(sha256(convert_to(token, 'UTF8')), 'hex')"
    )


def downgrade() -> None:
    # sha256은 되돌릴 수 없다. downgrade 시 기존 세션은 전부 무효가 되며,
    # 사용자는 재로그인해야 한다. 스키마 변경이 없으므로 아무것도 하지 않는다.
    pass
