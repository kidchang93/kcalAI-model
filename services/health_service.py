from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.health_model import MealItem, MealLog, UserGoal, UserProfile, WeightLog

ACTIVITY_FACTORS: dict[str, float] = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}

GOAL_ADJUSTMENTS: dict[str, int] = {
    "loss": -500,
    "maintain": 0,
    "gain": 300,
}

MEAL_TYPES = ("breakfast", "lunch", "dinner", "snack")


# ---- 목표 칼로리 산출 (Mifflin-St Jeor) ----

def calculate_target_kcal(profile: UserProfile, goal_type: str) -> int:
    age = datetime.now(UTC).year - profile.birth_year
    weight = float(profile.weight_kg)
    height = float(profile.height_cm)

    if profile.sex == "male":
        bmr = 10 * weight + 6.25 * height - 5 * age + 5
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age - 161

    tdee = bmr * ACTIVITY_FACTORS[profile.activity_level]
    return round(tdee + GOAL_ADJUSTMENTS[goal_type])


# ---- 프로필 ----

def get_profile(db: Session, user_id: int) -> UserProfile:
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    if profile is None:
        raise ValueError("신체 정보가 없습니다. 프로필을 먼저 등록해주세요.")
    return profile


def upsert_profile(
    db: Session,
    user_id: int,
    sex: str,
    birth_year: int,
    height_cm: float,
    weight_kg: float,
    activity_level: str,
) -> UserProfile:
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))

    if profile is None:
        profile = UserProfile(user_id=user_id)
        db.add(profile)

    profile.sex = sex
    profile.birth_year = birth_year
    profile.height_cm = Decimal(str(height_cm))
    profile.weight_kg = Decimal(str(weight_kg))
    profile.activity_level = activity_level

    db.commit()
    db.refresh(profile)
    return profile


# ---- 목표 ----

def get_open_goal(db: Session, user_id: int) -> UserGoal | None:
    return db.scalar(
        select(UserGoal).where(
            UserGoal.user_id == user_id,
            UserGoal.ended_at.is_(None),
        )
    )


def get_goal(db: Session, user_id: int) -> UserGoal:
    goal = get_open_goal(db, user_id)
    if goal is None:
        raise ValueError("설정된 목표가 없습니다. 목표를 먼저 등록해주세요.")
    return goal


def upsert_goal(
    db: Session,
    user_id: int,
    goal_type: str,
    target_kcal: int | None,
    target_weight_kg: float | None,
) -> UserGoal:
    if target_kcal is None:
        # 산출식은 프로필 입력값에 의존한다. 프로필이 없으면 산출할 수 없다.
        profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
        if profile is None:
            raise ValueError("신체 정보가 없어 목표 칼로리를 산출할 수 없습니다. 프로필을 먼저 등록해주세요.")
        target_kcal = calculate_target_kcal(profile, goal_type)

    now = datetime.now(UTC)

    # 이전에 열려 있던 목표를 닫아 이력을 보존한다 (단일 활성 목표 유지).
    previous = get_open_goal(db, user_id)
    if previous is not None:
        previous.ended_at = now

    goal = UserGoal(
        user_id=user_id,
        goal_type=goal_type,
        target_kcal=target_kcal,
        target_weight_kg=Decimal(str(target_weight_kg)) if target_weight_kg is not None else None,
        started_at=now,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


# ---- 홈 진행률 요약 ----

def _day_bounds(target_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(target_date, time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


def get_summary(db: Session, user_id: int, target_date: date) -> dict:
    start, end = _day_bounds(target_date)

    rows = db.execute(
        select(MealLog.meal_type, func.coalesce(func.sum(MealLog.total_kcal), 0))
        .where(
            MealLog.user_id == user_id,
            MealLog.deleted_at.is_(None),
            MealLog.logged_at >= start,
            MealLog.logged_at < end,
        )
        .group_by(MealLog.meal_type)
    ).all()

    breakdown = {meal_type: 0 for meal_type in MEAL_TYPES}
    for meal_type, total in rows:
        if meal_type in breakdown:
            breakdown[meal_type] = int(total)

    consumed = sum(breakdown.values())

    # 열린 목표가 없으면 target/remaining 은 null 이다. 목표 없음과 목표 0kcal 은 다르다.
    goal = get_open_goal(db, user_id)
    target = int(goal.target_kcal) if goal is not None else None
    remaining = target - consumed if target is not None else None

    return {
        "date": target_date.isoformat(),
        "target_kcal": target,
        "consumed_kcal": consumed,
        "remaining_kcal": remaining,
        "meals": breakdown,
    }


# ---- 끼니 ----

def create_meal(
    db: Session,
    user_id: int,
    meal_type: str,
    logged_at: datetime | None,
    photo_s3_key: str | None,
    items: list[dict],
) -> MealLog:
    total_kcal = sum(int(item["kcal"]) for item in items)

    meal = MealLog(
        user_id=user_id,
        meal_type=meal_type,
        logged_at=logged_at if logged_at is not None else datetime.now(UTC),
        photo_s3_key=photo_s3_key,
        total_kcal=total_kcal,
    )
    db.add(meal)
    db.flush()

    for item in items:
        db.add(
            MealItem(
                meal_log_id=meal.id,
                food_label=item["food_label"],
                serving_ratio=Decimal(str(item["serving_ratio"])),
                kcal=int(item["kcal"]),
                source=item["source"],
                confidence=(
                    Decimal(str(item["confidence"])) if item.get("confidence") is not None else None
                ),
            )
        )

    db.commit()
    db.refresh(meal)
    return meal


def list_meals(db: Session, user_id: int, target_date: date) -> list[MealLog]:
    start, end = _day_bounds(target_date)

    return list(
        db.scalars(
            select(MealLog)
            .where(
                MealLog.user_id == user_id,
                MealLog.deleted_at.is_(None),
                MealLog.logged_at >= start,
                MealLog.logged_at < end,
            )
            .order_by(MealLog.logged_at.asc())
        ).all()
    )


def soft_delete_meal(db: Session, user_id: int, meal_id: int) -> None:
    meal = db.scalar(
        select(MealLog).where(
            MealLog.id == meal_id,
            MealLog.deleted_at.is_(None),
        )
    )

    # 존재하지 않거나 남의 소유면 존재 자체를 숨긴다 (정보 노출 방지).
    if meal is None or meal.user_id != user_id:
        raise LookupError("끼니 기록을 찾을 수 없습니다.")

    meal.deleted_at = datetime.now(UTC)
    db.commit()


# ---- 체중 ----

def create_weight(
    db: Session,
    user_id: int,
    weight_kg: float,
    measured_at: datetime | None,
) -> WeightLog:
    log = WeightLog(
        user_id=user_id,
        weight_kg=Decimal(str(weight_kg)),
        measured_at=measured_at if measured_at is not None else datetime.now(UTC),
    )
    db.add(log)
    db.flush()

    # 프로필의 weight_kg 는 최신값 캐시다. 가장 최근 측정으로 동기화한다.
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    if profile is not None:
        latest_measured_at = db.scalar(
            select(func.max(WeightLog.measured_at)).where(WeightLog.user_id == user_id)
        )
        if latest_measured_at is not None and log.measured_at >= latest_measured_at:
            profile.weight_kg = Decimal(str(weight_kg))

    db.commit()
    db.refresh(log)
    return log


def list_weights(db: Session, user_id: int) -> list[WeightLog]:
    return list(
        db.scalars(
            select(WeightLog)
            .where(WeightLog.user_id == user_id)
            .order_by(WeightLog.measured_at.asc())
        ).all()
    )
