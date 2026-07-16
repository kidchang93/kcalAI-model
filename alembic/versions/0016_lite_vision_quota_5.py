"""raise Lite daily vision quota 3 -> 5

DATA_MODEL.md 20·22장. 무료(lite) 요금제의 일일 비전 쿼터를 3에서 5로 올린다.

0014_subscription_plans 의 시드는 건드리지 않는다 — 그 리비전은 fresh DB 에 3 을 넣고,
이 리비전이 그 뒤에서 5 로 수렴시킨다. 기존 배포 DB(이미 3 이 적재됨)도 이 UPDATE 로 5 가 된다.
히스토리 재작성이 아니라 신규 리비전으로 체인한다.

Revision ID: 0016_lite_vision_quota_5
Revises: 0015_kakao_login
Create Date: 2026-07-16
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0016_lite_vision_quota_5"
down_revision = "0015_kakao_login"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE plans SET daily_vision_quota = 5 WHERE code = 'lite'"))


def downgrade() -> None:
    op.execute(sa.text("UPDATE plans SET daily_vision_quota = 3 WHERE code = 'lite'"))
