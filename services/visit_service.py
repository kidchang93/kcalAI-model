"""진료 일정 (`docs/CARE_LOOP.md` §1·§4-3).

**예약하지 않는다.** 사용자가 자기 진료 일정을 적어 두면, 앱이 그 사이의 기록을 쌓고 진료
직전에 리포트를 꺼낼 수 있게 한다. 병원과는 아무것도 주고받지 않는다 — 방향이 반대라야
의료법 제27조 제3항(영리 목적 소개·알선 금지)에 닿지 않는다 (§3).

**예정 진료는 사용자당 하나로 둔다.** 여러 예약을 관리하는 캘린더가 아니라 "다음 한 바퀴가
언제 끝나는가"를 아는 것이 목적이라, 새로 넣으면 기존 예정을 덮어쓴다. 지난 진료 이력
(`visited_on`)은 같은 테이블에 남으므로 나중에 확장할 자리가 열려 있다.
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.health_model import CareVisit
from services.errors import BadRequestError

# 오타 방어 범위. 의학적 판단이 아니라 "2062년"처럼 손이 미끄러진 값을 막는 것이다.
# 과거를 조금 허용하는 이유는, 진료를 다녀온 뒤 다음 일정을 아직 못 정한 사람이 지난
# 날짜를 그대로 두는 것이 자연스럽기 때문이다.
_PAST_LIMIT_DAYS = 365
_FUTURE_LIMIT_DAYS = 365 * 5


class ScheduleOutOfRangeError(BadRequestError):
    pass


def get_next_visit(db: Session, user_id: int) -> CareVisit | None:
    """다녀오지 않은 예정 건. 없으면 None."""
    return db.execute(
        select(CareVisit)
        .where(CareVisit.user_id == user_id, CareVisit.visited_on.is_(None))
        .order_by(CareVisit.scheduled_on.asc().nulls_last(), CareVisit.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def set_next_visit(
    db: Session,
    user_id: int,
    scheduled_on: date,
    today: date,
    outcome: str | None = None,
) -> CareVisit:
    """예정 진료일을 등록하거나 바꾼다 (사용자당 하나이므로 upsert 가 아니라 덮어쓰기다)."""
    if scheduled_on < today - timedelta(days=_PAST_LIMIT_DAYS):
        raise ScheduleOutOfRangeError("진료 예정일을 다시 확인해주세요.")

    if scheduled_on > today + timedelta(days=_FUTURE_LIMIT_DAYS):
        raise ScheduleOutOfRangeError("진료 예정일을 다시 확인해주세요.")

    visit = get_next_visit(db, user_id)

    if visit is None:
        visit = CareVisit(user_id=user_id, scheduled_on=scheduled_on)
        db.add(visit)
    else:
        visit.scheduled_on = scheduled_on

    # None 은 "안 건드림", 빈 문자열은 "지움"이다 — 날짜만 고치는 요청이 메모를 날리면 안 된다.
    if outcome is not None:
        visit.outcome = outcome.strip() or None

    db.commit()
    db.refresh(visit)

    return visit


def clear_next_visit(db: Session, user_id: int) -> bool:
    """예정을 지운다. 지울 것이 없었으면 False.

    행을 삭제한다 — 아직 다녀오지 않은 예정이라 남겨 둘 이력이 없다. 진료를 다녀온 기록은
    `visited_on` 을 채우는 별도 흐름이 생길 때 다룬다.
    """
    visit = get_next_visit(db, user_id)

    if visit is None:
        return False

    db.delete(visit)
    db.commit()

    return True
