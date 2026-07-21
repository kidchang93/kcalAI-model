"""운동 기록 — 생성·조회·수정·삭제와 기간 집계 (docs/ACTIVITY_GUIDANCE.md 3-2).

식단(`health_service`의 끼니 로직)과 같은 규약을 따른다: 하루 경계는 **UTC 자정**, 삭제는 soft delete,
남의 기록은 **404 존재 은닉**. 두 도메인이 다르게 동작하면 앱이 날짜 경계를 두 번 다뤄야 한다.
"""

from datetime import date, datetime, time, timedelta

from timeutil import UTC

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.health_model import ExerciseLog, UserProfile
from services import fitness_rules


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
    recommended = fitness_rules.AEROBIC_MODERATE_MIN_MINUTES

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
        "recommended_min_minutes": recommended,
        "remaining_minutes": max(0, recommended - equivalent),
        "achieved": equivalent >= recommended,
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
