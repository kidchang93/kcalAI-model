"""진료 일정 (`docs/CARE_LOOP.md` §1·§4-3).

**예약하지 않는다.** 사용자가 자기 진료 일정을 적어 두면, 앱이 그 사이의 기록을 쌓고 진료
직전에 리포트를 꺼낼 수 있게 한다. 병원과는 아무것도 주고받지 않는다 — 방향이 반대라야
의료법 제27조 제3항(영리 목적 소개·알선 금지)에 닿지 않는다 (§3).

**예정 진료는 사용자당 하나로 둔다.** 여러 예약을 관리하는 캘린더가 아니라 "다음 한 바퀴가
언제 끝나는가"를 아는 것이 목적이다. 다만 **지난 진료는 덮어쓰지 않는다** (DATA_MODEL 32-6) — 예정일이
지난 행에 더 늦은 새 날짜가 오면 그 행을 `visited_on` 으로 닫고 새 예정 행을 만든다. 그날 물어본 것·들은
것이 그 진료의 기록이고, 리포트의 기본 기간("지난 진료부터 오늘")이 그 날짜에서 나온다.
"""

from datetime import date, timedelta

from sqlalchemy import func, or_, select
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
    scheduled_on: date | None,
    today: date,
    outcome: str | None = None,
    questions: str | None = None,
) -> CareVisit:
    """예정 진료의 날짜·메모를 바꾼다 (예정은 사용자당 하나).

    세 값 모두 **None 은 "안 건드림"**이다. 날짜 없이 메모만 오면 날짜 없는 예정 행을 만든다 —
    진료일을 정하기 전에 물어볼 것부터 담는 사람이 있다 (2026-10-05).

    **예정일이 지난 행에 더 늦은 날짜가 오면 그 행을 닫고 새 행을 만든다** (32-6). 같거나 이른 날짜는
    지난 날짜를 고치는 것이라 그대로 덮어쓴다 — 닫으면 오타 하나가 없던 진료를 기록에 남긴다. 닫을 때
    같이 온 `outcome`(진료에서 들은 것)은 **닫힌 행**에 적는다 — 다녀온 진료의 메모라서다. `questions`
    (물어볼 것)는 다음 진료의 것이라 새 행에 간다.
    """
    if scheduled_on is None and outcome is None and questions is None:
        raise BadRequestError("저장할 진료일이나 메모를 입력해주세요.")

    if scheduled_on is not None and not (
        today - timedelta(days=_PAST_LIMIT_DAYS)
        <= scheduled_on
        <= today + timedelta(days=_FUTURE_LIMIT_DAYS)
    ):
        raise ScheduleOutOfRangeError("진료 예정일을 다시 확인해주세요.")

    visit = get_next_visit(db, user_id)

    if (
        visit is not None
        and scheduled_on is not None
        and visit.scheduled_on is not None
        and visit.scheduled_on < today
        and scheduled_on > visit.scheduled_on
    ):
        visit.visited_on = visit.scheduled_on

        if outcome is not None:
            visit.outcome = outcome.strip() or None
            outcome = None

        visit = None

    if visit is None:
        visit = CareVisit(user_id=user_id)
        db.add(visit)

    if scheduled_on is not None:
        visit.scheduled_on = scheduled_on

    # 빈 문자열은 "지움"이다 — 날짜만 고치는 요청이 메모를 날리면 안 되고, 잘못 적은 메모를
    # 지울 방법도 있어야 한다.
    if outcome is not None:
        visit.outcome = outcome.strip() or None

    if questions is not None:
        visit.questions = questions.strip() or None

    db.commit()
    db.refresh(visit)

    return visit


def list_past_visits(
    db: Session, user_id: int, today: date, limit: int | None = None
) -> list[CareVisit]:
    """지난 진료 — 닫힌 행(`visited_on`)과, 아직 안 닫혔지만 예정일이 오늘 이전인 열린 행. 최신순.

    열린 행을 넣는 이유: 진료를 다녀온 뒤 다음 날짜를 아직 안 넣었으면 그 행은 닫히지 않은 채 지나 있다.
    그것도 다녀온 진료다 — 빼면 리포트의 "지난 진료일"이 한 바퀴 전으로 밀린다.
    날짜는 `visit_day()` 로 읽는다.
    """
    day = func.coalesce(CareVisit.visited_on, CareVisit.scheduled_on)
    return list(
        db.scalars(
            select(CareVisit)
            .where(
                CareVisit.user_id == user_id,
                or_(CareVisit.visited_on.is_not(None), CareVisit.scheduled_on < today),
            )
            .order_by(day.desc(), CareVisit.id.desc())
            .limit(limit)
        ).all()
    )


def visit_day(visit: CareVisit) -> date:
    return visit.visited_on or visit.scheduled_on


def recent_visit_dates(db: Session, user_id: int, today: date) -> tuple[date | None, date | None]:
    """(지난 진료일, 직전 진료일). 없으면 None — 리포트 기본 기간과 구간 비교가 쓴다."""
    days = [visit_day(visit) for visit in list_past_visits(db, user_id, today, limit=2)]
    days += [None, None]
    return days[0], days[1]


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
