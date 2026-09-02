"""진료 일정 — 케어 루프의 시작과 끝

`docs/CARE_LOOP.md` §1·§4-3. 이 앱의 완결은 "예약"이 아니라 **한 바퀴**인데, 그 바퀴가 어디서
시작해 어디서 끝나는지를 앱이 몰랐다. 진료일을 모르면 리포트를 언제 뽑아야 하는지도,
기록을 왜 지금 해야 하는지도 말할 수 없다 — `CARE_LOOP.md` §9 의 열린 결정 4번이 그것이다.

⚠️ **병원을 중개하지 않는다.** 이 테이블은 예약 시스템이 아니라 **사용자가 적어 두는 메모**다.
의료법 제27조 제3항(영리 목적 환자 소개·알선 금지)에 닿지 않으려면 방향이 반대여야 한다 —
우리가 환자를 병원에 보내는 게 아니라, 환자가 자기 일정을 적고 그 사이의 기록을 쌓는다
(`docs/CARE_LOOP.md` §3). 그래서 `clinic_label` 은 **자유 텍스트**이고 병원 마스터 DB 를
참조하지 않는다: 목록을 두는 순간 순서가 생기고, 순서에는 이해관계가 붙는다.

⚠️ **암호화하지 않는다.** 날짜는 D-day 계산과 정렬이 존재 이유라 암호화하면 쓸 수 없다.
`lab_results`(리비전 0027)와 같은 판단이다.

⚠️ `account_service.delete_account` 에 반드시 추가한다. FK 가 `ON DELETE NO ACTION` 이라
빠뜨리면 그 사용자는 **영구히 탈퇴할 수 없다**. 2026-07-16 에 `payments` 누락으로 실제 발생했다.

**지금 쓰는 컬럼은 `scheduled_on` 하나**다. 나머지(`questions`·`outcome`·`clinic_label`·
`report_from`/`report_to`)는 `CARE_LOOP.md` §4-3 에서 이미 설계가 확정된 것들이라 한 번에
만들어 둔다 — 컬럼 몇 개의 비용보다 마이그레이션을 또 도는 비용이 크다.

Revision ID: 0028_care_visits
Revises: 0027_lab_results
Create Date: 2026-08-19
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0028_care_visits"
down_revision = "0027_lab_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "care_visits",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        # 다음 진료 예정일. 지금 앱이 쓰는 유일한 값이다.
        sa.Column("scheduled_on", sa.Date(), nullable=True),
        # 지난 진료. null 이면 아직 다녀오지 않은 예정 건이다.
        sa.Column("visited_on", sa.Date(), nullable=True),
        # 사용자가 적는 자유 텍스트. **병원 DB 를 참조하지 않는다**(§3-1).
        sa.Column("clinic_label", sa.String(length=100), nullable=True),
        # 진료 전에 적어 두는 질문, 진료 후에 받아 적는 내용. 아직 API 로 열지 않았다.
        sa.Column("questions", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        # 이 진료에 지참한 리포트의 기간. 나중에 "그때 무엇을 보여 줬는가"를 되짚는 데 쓴다.
        sa.Column("report_from", sa.Date(), nullable=True),
        sa.Column("report_to", sa.Date(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # 조회는 늘 "이 사용자의 예정 건"이다 — 다녀온 것과 예정을 가르는 축이 visited_on 이라
    # 그 순서로 건다.
    op.create_index(
        "ix_care_visits_user_visited_scheduled",
        "care_visits",
        ["user_id", "visited_on", "scheduled_on"],
    )


def downgrade() -> None:
    op.drop_index("ix_care_visits_user_visited_scheduled", table_name="care_visits")
    op.drop_table("care_visits")
