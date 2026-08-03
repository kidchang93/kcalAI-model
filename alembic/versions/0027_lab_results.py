"""검사 수치 — 케어 루프를 닫는 결과 축

`docs/CARE_LOOP.md` §4. 지금까지 이 앱은 "나트륨 2,400mg 을 먹었다"까지만 말하고
"그래서 혈압이 어떻게 됐다"를 말하지 못했다. 식단 축만 있고 **결과 축이 없어 근거가
절반**이었고, `PRODUCT_STRATEGY.md` §0-2 의 지표 "검사 수치가 나빠졌을 때 되짚을 수
있었는가"도 식단 쪽만 되짚을 수 있는 반쪽 상태였다.

항목은 우리가 고른 것이 아니다 — 대한신장학회 e북 1권 I-20 「병원정기검사에서 확인해야 할
항목들」(p47–49)이 항목·정상범위·목표를 이미 정리해 두었고, 그것을 옮긴다.

⚠️ **암호화하지 않는다.** 민감정보지만 `user_health_profiles` 의 혈액형과 성격이 다르다 —
추이 정렬·기간 집계·식단 축과의 결합이 이 데이터의 존재 이유이고, 암호화하면 그 전부가
불가능하다. 질환(`user_conditions`)·병기(`ckd_stage`)를 비암호화 기능 키로 둔 것과 같은
판단이다. 대신 `sensitive_health` 동의 없이는 입력도 조회도 막는다.

⚠️ `account_service.delete_account` 에 반드시 추가한다. FK 가 `ON DELETE NO ACTION` 이라
빠뜨리면 그 사용자는 **영구히 탈퇴할 수 없다**(= 개인정보 파기 의무 위반). 2026-07-16 에
`payments` 누락으로 실제 발생했다.

Revision ID: 0027_lab_results
Revises: 0026_payment_refund
Create Date: 2026-08-03
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0027_lab_results"
down_revision = "0026_payment_refund"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lab_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        # 검사일이지 입력일이 아니다. 사용자는 지난 결과지를 나중에 옮겨 적는다.
        sa.Column("measured_on", sa.Date(), nullable=False),
        # 항목 코드. 값 목록은 `services/lab_panels.py` 가 단일 진실이다 — DB 에 enum 을 박으면
        # 항목을 늘릴 때마다 마이그레이션이 필요해진다(참조 데이터가 아니라 지침 인용이다).
        sa.Column("panel", sa.String(length=30), nullable=False),
        sa.Column("value", sa.Numeric(10, 2), nullable=False),
        # 단위는 서버가 panel 별로 고정한다. 사용자가 고르지 않는다 — mg/dL 과 mmol/L 을
        # 섞어 받으면 추이가 무의미해진다.
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False, server_default="manual"),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        # 같은 날 같은 항목은 하나. 결과지를 두 번 옮겨 적어도 덮어쓰기가 된다.
        sa.UniqueConstraint("user_id", "measured_on", "panel", name="uq_lab_results_user_date_panel"),
    )
    # 추이 조회가 (사용자, 항목, 날짜) 순이라 그 순서로 건다.
    op.create_index(
        "ix_lab_results_user_panel_date",
        "lab_results",
        ["user_id", "panel", "measured_on"],
    )


def downgrade() -> None:
    op.drop_index("ix_lab_results_user_panel_date", table_name="lab_results")
    op.drop_table("lab_results")
