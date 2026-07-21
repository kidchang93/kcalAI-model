"""운동 기록 — 생성·조회·수정·삭제와 기간 집계 (docs/ACTIVITY_GUIDANCE.md 3-2).

식단(`health_service`의 끼니 로직)과 같은 규약을 따른다: 하루 경계는 **UTC 자정**, 삭제는 soft delete,
남의 기록은 **404 존재 은닉**. 두 도메인이 다르게 동작하면 앱이 날짜 경계를 두 번 다뤄야 한다.
"""

from datetime import date, datetime, time, timedelta

from timeutil import UTC

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.health_model import ExerciseGoal, ExerciseLog, UserProfile
from services import fitness_rules


# 스트릭을 거슬러 볼 최대 주 수. 무한정 거슬러 올라가지 않는다(질의 비용·의미 둘 다).
STREAK_LOOKBACK_WEEKS = 26


def week_bounds(target_date: date) -> tuple[date, date]:
    """그 날짜가 속한 주(월~일)의 시작·끝. 한국 관습대로 **월요일 시작**이다."""
    start = target_date - timedelta(days=target_date.weekday())
    return start, start + timedelta(days=6)


def get_open_goal(db: Session, user_id: int) -> ExerciseGoal | None:
    return db.scalar(
        select(ExerciseGoal).where(
            ExerciseGoal.user_id == user_id,
            ExerciseGoal.ended_at.is_(None),
        )
    )


def resolve_goal(db: Session, user_id: int) -> dict:
    """사용자 목표. 없으면 **지침 권장량이 기본값**이다 (목표 미설정이 기능 부재가 되면 안 된다)."""
    goal = get_open_goal(db, user_id)

    if goal is None:
        return {
            "weekly_minutes": fitness_rules.AEROBIC_MODERATE_MIN_MINUTES,
            "weekly_strength_days": fitness_rules.STRENGTH_DAYS_MIN,
            "is_default": True,
        }

    return {
        "weekly_minutes": goal.weekly_minutes,
        "weekly_strength_days": goal.weekly_strength_days,
        "is_default": False,
    }


def upsert_goal(
    db: Session,
    user_id: int,
    weekly_minutes: int,
    weekly_strength_days: int,
) -> ExerciseGoal:
    """목표 변경. 이전 목표를 닫고 새 행을 연다 — 낮췄는지 높였는지가 이력에 남는다."""
    now = datetime.now(UTC)

    previous = get_open_goal(db, user_id)
    if previous is not None:
        previous.ended_at = now

    goal = ExerciseGoal(
        user_id=user_id,
        weekly_minutes=weekly_minutes,
        weekly_strength_days=weekly_strength_days,
        started_at=now,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def _day_bounds(target_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(target_date, time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


def _user_weight_kg(db: Session, user_id: int) -> float | None:
    # kcal 산출에 쓰는 체중. 프로필이 없으면 None → kcal 도 None 으로 남긴다(지어내지 않는다).
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    return float(profile.weight_kg) if profile is not None else None


def _resolve_fields(
    db: Session,
    user_id: int,
    exercise_type: str,
    duration_minutes: int,
    intensity: str | None,
    kcal: int | None,
) -> tuple[str, int | None]:
    """강도·kcal 을 확정한다. 알 수 없는 운동 종류는 ValueError → 400."""
    if exercise_type not in fitness_rules.EXERCISE_TYPES:
        raise ValueError("선택할 수 없는 운동 종류입니다.")

    resolved_intensity = intensity or fitness_rules.default_intensity(exercise_type)

    # 사용자가 kcal 을 주면 그 값을 존중한다 (target_kcal 과 같은 규약).
    if kcal is None:
        kcal = fitness_rules.estimate_exercise_kcal(
            exercise_type, duration_minutes, _user_weight_kg(db, user_id)
        )

    return resolved_intensity, kcal


def create_exercise(
    db: Session,
    user_id: int,
    exercise_type: str,
    duration_minutes: int,
    intensity: str | None,
    kcal: int | None,
    performed_at: datetime | None,
    memo: str | None,
) -> ExerciseLog:
    resolved_intensity, resolved_kcal = _resolve_fields(
        db, user_id, exercise_type, duration_minutes, intensity, kcal
    )

    exercise = ExerciseLog(
        user_id=user_id,
        performed_at=performed_at or datetime.now(UTC),
        exercise_type=exercise_type,
        duration_minutes=duration_minutes,
        intensity=resolved_intensity,
        kcal=resolved_kcal,
        source="manual",
        memo=memo,
    )
    db.add(exercise)
    db.commit()
    db.refresh(exercise)
    return exercise


def list_exercises(db: Session, user_id: int, target_date: date) -> list[ExerciseLog]:
    start, end = _day_bounds(target_date)
    return list(
        db.scalars(
            select(ExerciseLog)
            .where(
                ExerciseLog.user_id == user_id,
                ExerciseLog.deleted_at.is_(None),
                ExerciseLog.performed_at >= start,
                ExerciseLog.performed_at < end,
            )
            .order_by(ExerciseLog.performed_at.asc(), ExerciseLog.id.asc())
        ).all()
    )


def _get_owned(db: Session, user_id: int, exercise_id: int) -> ExerciseLog:
    """남의 기록·삭제된 기록·없는 기록은 전부 같은 오류다 — 존재를 알려주지 않는다."""
    exercise = db.scalar(
        select(ExerciseLog).where(
            ExerciseLog.id == exercise_id,
            ExerciseLog.user_id == user_id,
            ExerciseLog.deleted_at.is_(None),
        )
    )
    if exercise is None:
        raise LookupError("운동 기록을 찾을 수 없습니다.")
    return exercise


def update_exercise(
    db: Session,
    user_id: int,
    exercise_id: int,
    exercise_type: str,
    duration_minutes: int,
    intensity: str | None,
    kcal: int | None,
    performed_at: datetime | None,
    memo: str | None,
) -> ExerciseLog:
    exercise = _get_owned(db, user_id, exercise_id)
    resolved_intensity, resolved_kcal = _resolve_fields(
        db, user_id, exercise_type, duration_minutes, intensity, kcal
    )

    exercise.exercise_type = exercise_type
    exercise.duration_minutes = duration_minutes
    exercise.intensity = resolved_intensity
    exercise.kcal = resolved_kcal
    exercise.memo = memo
    # 끼니 PUT 과 같은 예외: performed_at 을 생략하면 기존 시각을 유지한다(not-null 컬럼이라 null 교체 불가).
    if performed_at is not None:
        exercise.performed_at = performed_at

    db.commit()
    db.refresh(exercise)
    return exercise


def delete_exercise(db: Session, user_id: int, exercise_id: int) -> None:
    exercise = _get_owned(db, user_id, exercise_id)
    exercise.deleted_at = datetime.now(UTC)
    db.commit()


def _equivalent_minutes(row: ExerciseLog) -> int:
    """지침 환산 — 고강도 1분 = 중강도 2분. 저강도는 권장량에 들어가지 않는다."""
    if row.intensity == "vigorous":
        return row.duration_minutes * fitness_rules.VIGOROUS_TO_MODERATE_FACTOR
    if row.intensity == "moderate":
        return row.duration_minutes
    return 0


def calculate_streak(db: Session, user_id: int, today: date, weekly_target: int) -> int:
    """목표를 연속으로 달성한 주 수 (월요일 시작).

    **이번 주는 이미 달성했을 때만 센다** — 아직 기회가 남은 주를 실패로 세면 진행 중인 주가
    스트릭을 끊어 버린다. 미달성이면 지난 주부터 거슬러 올라간다.
    """
    if weekly_target <= 0:
        return 0

    this_week_start, _ = week_bounds(today)
    oldest = this_week_start - timedelta(weeks=STREAK_LOOKBACK_WEEKS)

    rows = list(
        db.scalars(
            select(ExerciseLog).where(
                ExerciseLog.user_id == user_id,
                ExerciseLog.deleted_at.is_(None),
                ExerciseLog.performed_at >= datetime.combine(oldest, time.min, tzinfo=UTC),
            )
        ).all()
    )

    per_week: dict[date, int] = {}
    for row in rows:
        week_start, _ = week_bounds(row.performed_at.astimezone(UTC).date())
        per_week[week_start] = per_week.get(week_start, 0) + _equivalent_minutes(row)

    streak = 0
    cursor = this_week_start

    # 진행 중인 주: 달성했으면 세고, 아니면 넘어가서 지난 주부터 본다.
    if per_week.get(cursor, 0) >= weekly_target:
        streak += 1
    cursor -= timedelta(weeks=1)

    while cursor >= oldest and per_week.get(cursor, 0) >= weekly_target:
        streak += 1
        cursor -= timedelta(weeks=1)

    return streak


def get_summary(db: Session, user_id: int, start_date: date, end_date: date) -> dict:
    """기간 집계 + 권장 대비 달성률.

    지침(주 150~300분)과 바로 대조할 수 있도록 강도별 분을 합산하고,
    **고강도 1분 = 중강도 2분**(KPAG)으로 환산한 단일 축을 함께 준다.
    """
    if end_date < start_date:
        raise ValueError("종료일이 시작일보다 빠릅니다. 날짜 범위를 확인해주세요.")

    start, _ = _day_bounds(start_date)
    _, end = _day_bounds(end_date)

    rows = list(
        db.scalars(
            select(ExerciseLog).where(
                ExerciseLog.user_id == user_id,
                ExerciseLog.deleted_at.is_(None),
                ExerciseLog.performed_at >= start,
                ExerciseLog.performed_at < end,
            )
        ).all()
    )

    minutes = {intensity: 0 for intensity in fitness_rules.INTENSITIES}
    total_kcal = 0
    # 근력운동은 분이 아니라 '주 몇 일'이라 날짜 집합으로 센다 (같은 날 두 번 해도 1일).
    strength_days: set[date] = set()

    for row in rows:
        if row.intensity in minutes:
            minutes[row.intensity] += row.duration_minutes
        total_kcal += row.kcal or 0
        if row.exercise_type == fitness_rules.STRENGTH_EXERCISE_TYPE:
            strength_days.add(row.performed_at.astimezone(UTC).date())

    equivalent = (
        minutes["moderate"]
        + minutes["vigorous"] * fitness_rules.VIGOROUS_TO_MODERATE_FACTOR
    )

    # 달성 판정의 기준은 **사용자 목표**다. 목표가 없으면 지침 권장량이 기본값으로 들어온다.
    goal = resolve_goal(db, user_id)
    target = goal["weekly_minutes"]

    return {
        "start_date": start_date,
        "end_date": end_date,
        "light_minutes": minutes["light"],
        "moderate_minutes": minutes["moderate"],
        "vigorous_minutes": minutes["vigorous"],
        "equivalent_moderate_minutes": equivalent,
        "strength_days": len(strength_days),
        "total_kcal": total_kcal,
        "exercise_count": len(rows),
        "target_minutes": target,
        "target_strength_days": goal["weekly_strength_days"],
        "goal_is_default": goal["is_default"],
        # 지침 권장 하한도 함께 준다 — 목표를 낮게 잡았어도 지침이 뭔지 볼 수 있어야 한다.
        "recommended_min_minutes": fitness_rules.AEROBIC_MODERATE_MIN_MINUTES,
        "remaining_minutes": max(0, target - equivalent),
        "achieved": equivalent >= target,
        # 스트릭은 '오늘이 속한 주' 기준이라 조회 구간과 무관하게 계산한다.
        "streak_weeks": calculate_streak(db, user_id, datetime.now(UTC).date(), target),
        "notice": fitness_rules.ACTIVITY_NOTICE,
    }


def to_response(exercise: ExerciseLog) -> dict:
    """표시명을 서버가 붙여 준다 — 앱이 코드→라벨 표를 따로 갖지 않게."""
    return {
        "id": exercise.id,
        "exercise_type": exercise.exercise_type,
        "exercise_type_label": fitness_rules.exercise_type_label(exercise.exercise_type)
        or exercise.exercise_type,
        "duration_minutes": exercise.duration_minutes,
        "intensity": exercise.intensity,
        "kcal": exercise.kcal,
        "source": exercise.source,
        "memo": exercise.memo,
        "performed_at": exercise.performed_at,
    }


def list_exercise_types() -> list[dict]:
    return [
        {"code": code, "label": label, "default_intensity": intensity}
        for code, (label, _met, intensity) in fitness_rules.EXERCISE_TYPES.items()
    ]
