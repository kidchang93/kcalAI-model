"""payments.user_id 를 nullable 로 — 탈퇴 시 원장을 익명화해 보존하기 위함

회원 탈퇴는 개인정보 파기(개인정보보호법 제21조)지만, **결제 원장은 거래 기록**이라 함께 지울 수
없다(전자상거래법 제6조의 대금결제 기록 보존). 두 의무를 동시에 지키는 방법은 원장 행은 남기되
**개인 식별자를 끊는 것**이다 — `user_id` 를 NULL 로 만들면 그 행은 더 이상 특정 개인과 연결되지
않으면서 주문번호·금액·일시·결제수단은 감사 근거로 남는다.

`billing_keys` 는 반대다. 카드를 다시 긁을 수 있는 **자격증명**이라 보존할 이유가 없고, 탈퇴 시
물리 삭제한다(`services/account_service.py`).

이 리비전 전까지 `payments.user_id` 는 NOT NULL 이었고, FK 는 ON DELETE NO ACTION 이라 결제 이력이
있는 회원의 `DELETE /api/me` 가 **ForeignKeyViolation → 500** 으로 실패했다(= 탈퇴 불가). 삭제 연쇄
코드는 2026-07-11 작성이고 payments·billing_keys 는 0017(2026-07-16)에 추가돼 목록에서 누락됐다.

FK 는 그대로 NO ACTION 으로 둔다. ON DELETE SET NULL 로 DB 에 맡기면 "익명화한다"는 의도가 코드에서
사라지고, 실수로 users 를 지웠을 때 원장이 조용히 끊기는 것을 막지 못한다 — 삭제 연쇄는
account_service 가 명시적으로 수행한다.

Revision ID: 0018_payments_user_nullable
Revises: 0017_payments_billing
Create Date: 2026-07-16
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0018_payments_user_nullable"
down_revision = "0017_payments_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "payments",
        "user_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    # 익명화된 행(user_id IS NULL)이 있으면 NOT NULL 로 되돌릴 수 없다. 되돌리려면 그 행들을
    # 어떻게 할지(삭제/이관) 먼저 정해야 하므로, 조용히 지우지 않고 실패시킨다.
    orphaned = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM payments WHERE user_id IS NULL")
    )

    if orphaned:
        raise RuntimeError(
            f"익명화된 결제 원장 {orphaned}건이 있어 되돌릴 수 없습니다. "
            "탈퇴 회원의 거래 기록이라 임의 삭제하면 보존 의무를 어깁니다."
        )

    op.alter_column(
        "payments",
        "user_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
