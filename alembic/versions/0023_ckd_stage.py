"""user_health_profiles.ckd_stage — 신장병 병기(투석 여부)

`CKD_NUTRITION.md` §4에 보류로 남겨 두었던 항목 중 **병기 필드만** 연다. 단백질 개인 목표
(g/kg) 산출은 여전히 하지 않는다 — 그건 처방에 근접한다.

병기가 필요한 이유는 하나다: **나트륨 1일 상한이 병기에서 갈린다**(비투석 2,000 · 투석 3,000).
병기를 모르면 CKD 사용자에게는 상한을 제시할 수 없어 "오늘 얼마나 먹었는지"가 수치로만 남는다.

**암호화하지 않는다.** blood_type·rh 와 같은 테이블이지만 성격이 다르다 — 이 값은 조회 시
기준선을 고르는 **기능 키**이고, condition·allergen 을 평문으로 두기로 한 판단과 같은
이유다(리비전 0013 의 범위 정정 이력).

값은 nondialysis / hemodialysis / peritoneal, 미입력(모름)은 NULL 이다. 모름을 별도 코드로
두지 않는 이유는 NULL 과 뜻이 같아서다.

Revision ID: 0023_ckd_stage
Revises: 0022_group_challenges
Create Date: 2026-07-23
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0023_ckd_stage"
down_revision = "0022_group_challenges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_health_profiles",
        sa.Column("ckd_stage", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_health_profiles", "ckd_stage")
