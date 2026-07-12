"""민감정보(혈액형·Rh) 컬럼 앱 레이어 암호화

user_health_profiles.blood_type·rh를 AES-256-GCM 암호문(base64)으로 저장한다.
- 컬럼을 String(255)로 넓힌다 (암호문이 원문보다 길다).
- 기존 평문 행을 crypto.encrypt로 일괄 암호화한다.

범위는 blood_type·rh 두 컬럼뿐이다. condition·allergen은 참조 테이블 FK·JOIN·
추천/경고 필터에 쓰이는 기능 키라 평문 코드로 유지한다 (암호화 대상 아님).

이 리비전은 평문 상태에서 정확히 한 번 실행된다. crypto가 쓰는 HEALTH_ENCRYPTION_KEY가
앱과 동일해야 복호화된다.

Revision ID: 0013_encrypt_health_fields
Revises: 0012_hash_session_tokens
Create Date: 2026-07-12
"""

import sqlalchemy as sa

from alembic import op
from crypto import decrypt, encrypt

# revision identifiers, used by Alembic.
revision = "0013_encrypt_health_fields"
down_revision = "0012_hash_session_tokens"
branch_labels = None
depends_on = None

# (테이블, 컬럼, 원래 길이) — downgrade에서 원복에 쓴다.
_TARGETS = [
    ("user_health_profiles", "blood_type", 10),
    ("user_health_profiles", "rh", 1),
]


def _transform_existing(table: str, col: str, fn) -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(f"SELECT id, {col} FROM {table} WHERE {col} IS NOT NULL")
    ).all()
    for row_id, value in rows:
        conn.execute(
            sa.text(f"UPDATE {table} SET {col} = :v WHERE id = :id"),
            {"v": fn(value), "id": row_id},
        )


def upgrade() -> None:
    # 1) 컬럼을 넓힌다 (암호문 수용).
    for table, col, _ in _TARGETS:
        op.alter_column(table, col, type_=sa.String(255))

    # 2) 기존 평문을 암호화.
    for table, col, _ in _TARGETS:
        _transform_existing(table, col, encrypt)


def downgrade() -> None:
    # 1) 복호화해 평문으로 되돌린다 (동일 키 필요).
    for table, col, _ in _TARGETS:
        _transform_existing(table, col, decrypt)

    # 2) 컬럼 길이 원복.
    for table, col, length in _TARGETS:
        op.alter_column(table, col, type_=sa.String(length))
