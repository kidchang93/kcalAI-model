"""검사 수치 CRUD (`docs/CARE_LOOP.md` §4).

**해석하지 않는다.** 정상/비정상을 판정하거나 경고를 만들지 않고, 값을 그대로 남긴다.
지침이 정한 범위는 `lab_panels.reference` 문장으로 나란히 놓을 뿐이다 — 범위를 옆에 두는
것과 "정상입니다"라고 말하는 것은 다르고, 뒤의 것은 진단이다
(`docs/CKD_NUTRITION.md` §'노출 원칙').
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from models.health_model import LabResult
from services import lab_panels
from services.errors import BadRequestError


class UnknownPanelError(BadRequestError):
    pass


class ValueOutOfRangeError(BadRequestError):
    pass


def save_result(
    db: Session,
    user_id: int,
    measured_on: date,
    panel: str,
    value: Decimal,
    note: str | None = None,
    source: str = "manual",
) -> LabResult:
    """같은 날 같은 항목이면 **덮어쓴다**.

    결과지를 두 번 옮겨 적는 것은 실수지 새 검사가 아니다. 오타를 고치려고 지웠다 넣는
    수고를 시키지 않는다.
    """
    definition = lab_panels.get_panel(panel)

    if definition is None:
        raise UnknownPanelError("알 수 없는 검사 항목입니다.")

    # 음수와 터무니없는 값만 막는다. 이건 오타 방어이지 의학적 판정이 아니다 —
    # "이 수치는 위험합니다" 같은 판단은 하지 않는다.
    if value <= 0 or float(value) > lab_panels.max_value(panel):
        raise ValueOutOfRangeError("입력한 수치를 다시 확인해주세요.")

    statement = (
        insert(LabResult)
        .values(
            user_id=user_id,
            measured_on=measured_on,
            panel=panel,
            value=value,
            unit=definition.unit,
            source=source,
            note=note,
        )
        .on_conflict_do_update(
            constraint="uq_lab_results_user_date_panel",
            set_={"value": value, "unit": definition.unit, "note": note, "source": source},
        )
        .returning(LabResult)
    )

    row = db.execute(statement).scalar_one()
    db.commit()
    db.refresh(row)

    return row


def list_results(
    db: Session,
    user_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    panel: str | None = None,
) -> list[LabResult]:
    """최신 검사일 순. 같은 날이면 항목 코드 순으로 결정적이게 정렬한다."""
    conditions = [LabResult.user_id == user_id]

    if start_date is not None:
        conditions.append(LabResult.measured_on >= start_date)

    if end_date is not None:
        conditions.append(LabResult.measured_on <= end_date)

    if panel is not None:
        conditions.append(LabResult.panel == panel)

    return list(
        db.scalars(
            select(LabResult)
            .where(*conditions)
            .order_by(LabResult.measured_on.desc(), LabResult.panel.asc())
        ).all()
    )


def delete_result(db: Session, user_id: int, result_id: int) -> bool:
    """남의 것·없는 것은 똑같이 False — 존재를 알려 주지 않는다(다른 삭제 라우트와 같은 규약)."""
    deleted = db.execute(
        delete(LabResult).where(LabResult.id == result_id, LabResult.user_id == user_id)
    ).rowcount

    db.commit()

    return deleted > 0
