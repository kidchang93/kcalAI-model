from datetime import date, datetime, timedelta

from timeutil import UTC
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from models.health_model import MealItem, MealLog, UserGoal, UserProfile, WeightLog
from schemas.health_schema import ProfileResponse
from services import day_nutrition, fitness_rules, nutrition_service
from services.errors import BadRequestError, NotFoundError

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
        **ProfileResponse.model_validate(profile).model_dump(),
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
        raise NotFoundError("신체 정보가 없습니다. 프로필을 먼저 등록해주세요.")
    return profile


# 만 14세 미만은 가입을 받지 않는다 (`docs/LEGAL_COMPLIANCE.md` §1).
#
# 개인정보 보호법 제22조의2 — 만 14세 미만 아동의 개인정보를 처리하려면 법정대리인의 동의를
# 받고 **확인**해야 한다. 위반은 5년 이하 징역 또는 5천만원 이하 벌금이다. 우리는 질병·알러지라는
# **민감정보**까지 다루므로 요건이 더 무겁다.
#
# 동의 절차를 만드는 대신 차단을 택한 이유는 **대상이 아니어서**다 — 이 앱의 식이 규칙은 전부
# 성인 지침(KSN·KDA·KSH)에서 왔고, 소아 신장질환·소아 당뇨는 기준이 다르다. 차단하지 않으면
# 아이에게 성인 기준을 적용하게 된다.
#
# ⚠️ **판정은 연 나이다.** 우리는 생년월일이 아니라 출생연도만 수집하므로(최소수집), 생일이
# 지나지 않은 만 13세가 통과할 수 있다. 이 한계는 문서와 약관에 적는다.
MIN_SIGNUP_AGE = 14

AGE_RESTRICTION_MESSAGE = (
    "만 14세 미만은 가입할 수 없습니다. "
    "이 서비스는 성인 진료지침을 기준으로 식단을 안내하며, 질병 정보를 다룹니다."
)


def _ensure_minimum_age(birth_year: int) -> None:
    """연 나이가 기준 미만이면 거부한다 (`MIN_SIGNUP_AGE` 주석의 근거)."""
    if datetime.now(UTC).year - birth_year < MIN_SIGNUP_AGE:
        raise BadRequestError(AGE_RESTRICTION_MESSAGE)


def upsert_profile(
    db: Session,
    user_id: int,
    sex: str,
    birth_year: int,
    height_cm: float,
    weight_kg: float,
    activity_level: str,
) -> UserProfile:
    _ensure_minimum_age(birth_year)

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
        raise NotFoundError("설정된 목표가 없습니다. 목표를 먼저 등록해주세요.")
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
            raise BadRequestError("신체 정보가 없어 목표 칼로리를 산출할 수 없습니다. 프로필을 먼저 등록해주세요.")
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

def get_summary(db: Session, user_id: int, target_date: date) -> dict:
    rows = db.execute(
        select(MealLog.meal_type, func.coalesce(func.sum(MealLog.total_kcal), 0))
        .where(*MealLog.live_between(user_id, target_date, target_date))
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
        # 질환 축(나트륨·칼륨·인) 하루 누적. 해당 질환이 없으면 None — 그때 홈은 지금까지처럼
        # 칼로리만 보여준다. 만성질환자에게는 kcal 보다 이 숫자가 중요하다(PRODUCT_STRATEGY §1).
        "nutrients": day_nutrition.get_day_nutrient_axes(db, user_id, target_date),
    }


# ---- 주/월 추이 ----

def get_trends(db: Session, user_id: int, start_date: date, end_date: date) -> dict:
    if end_date < start_date:
        raise BadRequestError("종료일이 시작일보다 빠릅니다. 날짜 범위를 확인해주세요.")

    total_days = (end_date - start_date).days + 1
    if total_days > TRENDS_MAX_DAYS:
        raise BadRequestError(f"조회 범위는 최대 {TRENDS_MAX_DAYS}일입니다. 범위를 줄여 다시 시도해주세요.")

    # 세션 타임존과 무관하게 summary 와 같은 UTC 날짜 경계로 절단해 GROUP BY 한다.
    # 날짜 수만큼 쿼리를 반복하지 않는다 — 단일 쿼리 집계.
    day_column = func.date(func.timezone("UTC", MealLog.logged_at))
    rows = db.execute(
        select(
            day_column.label("day"),
            func.coalesce(func.sum(MealLog.total_kcal), 0),
            func.count(MealLog.id),
        )
        .where(*MealLog.live_between(user_id, start_date, end_date))
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
        "nutrients": day_nutrition.get_period_nutrient_axes(db, user_id, start_date, end_date),
    }


# ---- 끼니 ----

def _total_kcal(items: list[dict]) -> int:
    return sum(int(item["kcal"]) for item in items)


# 스냅샷으로 남길 축 → FoodNutrition 컬럼 (리비전 0025).
_SNAPSHOT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("sodium_mg", "sodium_mg"),
    ("potassium_mg", "potassium_mg"),
    ("phosphorus_mg", "phosphorus_mg"),
    ("sugar_g", "sugar_g"),
)


def _nutrient_snapshot(db: Session, food_label: str, serving_ratio: Decimal) -> dict[str, Decimal | None]:
    """기록 시점의 영양 수치를 **먹은 양 기준**으로 굳힌다 (리비전 0025).

    조회 규약은 경고 판정과 같다 — 정확·공백무시 일치만 쓰고 유사도는 쓰지 않는다. 두 곳이
    다른 방식으로 찾으면 "경고는 떴는데 합계에는 안 잡히는" 음식이 생긴다.
    """
    row = nutrition_service.measured_nutrition_for(db, food_label)

    if row is None:
        return {name: None for name, _ in _SNAPSHOT_COLUMNS}

    snapshot: dict[str, Decimal | None] = {}
    for name, source_column in _SNAPSHOT_COLUMNS:
        value = getattr(row, source_column)
        snapshot[name] = (
            None if value is None else (Decimal(value) * serving_ratio).quantize(Decimal("0.1"))
        )

    return snapshot


def _insert_meal_items(db: Session, meal_log_id: int, items: list[dict]) -> None:
    for item in items:
        serving_ratio = Decimal(str(item["serving_ratio"]))
        db.add(
            MealItem(
                meal_log_id=meal_log_id,
                food_label=item["food_label"],
                serving_ratio=serving_ratio,
                kcal=int(item["kcal"]),
                source=item["source"],
                confidence=(
                    Decimal(str(item["confidence"])) if item.get("confidence") is not None else None
                ),
                **_nutrient_snapshot(db, item["food_label"], serving_ratio),
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
    meal = _get_own_meal(db, user_id, meal_id)

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
    return list(
        db.scalars(
            select(MealLog)
            .where(*MealLog.live_between(user_id, target_date, target_date))
            # id 를 두 번째 키로 둔다 — 같은 날 기록은 `logged_at` 이 **같은 값으로 몰린다**
            # (앱이 과거 날짜를 UTC 정오로 앵커한다, DATA_MODEL 4장). 시각만으로 정렬하면
            # 순서가 DB 물리 순서에 맡겨져, 항목을 더한 끼니(UPDATE)가 목록 맨 뒤로 밀린다 —
            # 사용자에겐 "방금 추가한 게 사라진" 것으로 보인다.
            .order_by(MealLog.logged_at.asc(), MealLog.id.asc())
        ).all()
    )


def soft_delete_meal(db: Session, user_id: int, meal_id: int) -> None:
    meal = _get_own_meal(db, user_id, meal_id)
    meal.deleted_at = datetime.now(UTC)
    db.commit()


def _get_own_meal(db: Session, user_id: int, meal_id: int) -> MealLog:
    meal = db.scalar(
        select(MealLog).where(
            MealLog.id == meal_id,
            MealLog.deleted_at.is_(None),
        )
    )

    # 존재하지 않거나 남의 소유면 존재 자체를 숨긴다 (정보 노출 방지).
    if meal is None or meal.user_id != user_id:
        raise NotFoundError("끼니 기록을 찾을 수 없습니다.")

    return meal


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
