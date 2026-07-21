from datetime import date, datetime, time, timedelta

from timeutil import UTC
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from models.health_model import MealItem, MealLog, UserGoal, UserProfile, WeightLog
from services import fitness_rules

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

# 추이 조회 상한 (양끝 포함). 3개월 그래프까지만 허용한다.
TRENDS_MAX_DAYS = 92


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


def build_profile_response(profile: UserProfile) -> dict:
    """프로필 + 응답 시 계산하는 파생 지표(BMI·활동 권고).

    저장하지 않는 이유는 펫 `recommended_kcal`과 같다 — 키·체중이 바뀌면 즉시 따라와야 하고,
    저장하면 두 값이 어긋난다 (docs/ACTIVITY_GUIDANCE.md 3-1).
    앱이 같은 산식을 재구현하지 않도록 **서버가 단일 진실**이다.
    """
    bmi = fitness_rules.calculate_bmi(float(profile.height_cm), float(profile.weight_kg))
    category = fitness_rules.bmi_category(bmi)
    age = datetime.now(UTC).year - profile.birth_year

    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "sex": profile.sex,
        "birth_year": profile.birth_year,
        "height_cm": float(profile.height_cm),
        "weight_kg": float(profile.weight_kg),
        "activity_level": profile.activity_level,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
        "bmi": bmi,
        "bmi_category": category,
        "bmi_category_label": fitness_rules.bmi_category_label(category),
        "bmi_notice": fitness_rules.BMI_NOTICE if bmi is not None else None,
        "activity_guide": fitness_rules.activity_guide(age),
    }


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


# ---- 주/월 추이 ----

def get_trends(db: Session, user_id: int, start_date: date, end_date: date) -> dict:
    if end_date < start_date:
        raise ValueError("종료일이 시작일보다 빠릅니다. 날짜 범위를 확인해주세요.")

    total_days = (end_date - start_date).days + 1
    if total_days > TRENDS_MAX_DAYS:
        raise ValueError(f"조회 범위는 최대 {TRENDS_MAX_DAYS}일입니다. 범위를 줄여 다시 시도해주세요.")

    start, _ = _day_bounds(start_date)
    _, end = _day_bounds(end_date)

    # 세션 타임존과 무관하게 summary 와 같은 UTC 날짜 경계로 절단해 GROUP BY 한다.
    # 날짜 수만큼 쿼리를 반복하지 않는다 — 단일 쿼리 집계.
    day_column = func.date(func.timezone("UTC", MealLog.logged_at))
    rows = db.execute(
        select(
            day_column.label("day"),
            func.coalesce(func.sum(MealLog.total_kcal), 0),
            func.count(MealLog.id),
        )
        .where(
            MealLog.user_id == user_id,
            MealLog.deleted_at.is_(None),
            MealLog.logged_at >= start,
            MealLog.logged_at < end,
        )
        .group_by(day_column)
    ).all()

    aggregated = {day: (int(kcal), int(count)) for day, kcal, count in rows}

    # 기록 없는 날도 0 으로 채운다 (그래프용 — 빈 날이 빠지면 축이 어긋난다).
    days = []
    for offset in range(total_days):
        day = start_date + timedelta(days=offset)
        consumed_kcal, meal_count = aggregated.get(day, (0, 0))
        days.append(
            {
                "date": day.isoformat(),
                "consumed_kcal": consumed_kcal,
                "meal_count": meal_count,
            }
        )

    # 열린 목표가 없으면 null 이다. 목표 없음과 목표 0kcal 은 다르다 (summary 와 동일 규칙).
    goal = get_open_goal(db, user_id)
    target = int(goal.target_kcal) if goal is not None else None

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "target_kcal": target,
        "days": days,
    }


# ---- 끼니 ----

def _total_kcal(items: list[dict]) -> int:
    return sum(int(item["kcal"]) for item in items)


def _insert_meal_items(db: Session, meal_log_id: int, items: list[dict]) -> None:
    for item in items:
        db.add(
            MealItem(
                meal_log_id=meal_log_id,
                food_label=item["food_label"],
                serving_ratio=Decimal(str(item["serving_ratio"])),
                kcal=int(item["kcal"]),
                source=item["source"],
                confidence=(
                    Decimal(str(item["confidence"])) if item.get("confidence") is not None else None
                ),
            )
        )


def create_meal(
    db: Session,
    user_id: int,
    meal_type: str,
    logged_at: datetime | None,
    photo_s3_key: str | None,
    items: list[dict],
) -> MealLog:
    meal = MealLog(
        user_id=user_id,
        meal_type=meal_type,
        logged_at=logged_at if logged_at is not None else datetime.now(UTC),
        photo_s3_key=photo_s3_key,
        total_kcal=_total_kcal(items),
    )
    db.add(meal)
    db.flush()

    _insert_meal_items(db, meal.id, items)

    db.commit()
    db.refresh(meal)
    return meal


def update_meal(
    db: Session,
    user_id: int,
    meal_id: int,
    meal_type: str,
    logged_at: datetime | None,
    photo_s3_key: str | None,
    items: list[dict],
) -> MealLog:
    meal = db.scalar(
        select(MealLog).where(
            MealLog.id == meal_id,
            MealLog.deleted_at.is_(None),
        )
    )

    # 존재하지 않거나 남의 소유면 존재 자체를 숨긴다 (soft_delete_meal 과 같은 규칙).
    if meal is None or meal.user_id != user_id:
        raise LookupError("끼니 기록을 찾을 수 없습니다.")

    meal.meal_type = meal_type
    # 전체 교체지만 logged_at 은 not-null 컬럼이므로 생략 시 기존 기록 시각을 유지한다.
    if logged_at is not None:
        meal.logged_at = logged_at
    meal.photo_s3_key = photo_s3_key
    meal.total_kcal = _total_kcal(items)

    # 항목은 전체 교체 — 기존 행을 지우고 다시 넣는다. 합계는 meal_items 가 단일 진실이다.
    db.execute(delete(MealItem).where(MealItem.meal_log_id == meal.id))
    _insert_meal_items(db, meal.id, items)

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
