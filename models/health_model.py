from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    sex: Mapped[str] = mapped_column(String(10), nullable=False)
    birth_year: Mapped[int] = mapped_column(Integer, nullable=False)
    height_cm: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    activity_level: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UserGoal(Base):
    __tablename__ = "user_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    goal_type: Mapped[str] = mapped_column(String(10), nullable=False)
    target_kcal: Mapped[int] = mapped_column(Integer, nullable=False)
    target_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 1), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 목표 변경 시 이전 행을 닫는다 (이력 보존). 열려 있는 목표는 NULL.
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MealLog(Base):
    __tablename__ = "meal_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    logged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
    meal_type: Mapped[str] = mapped_column(String(10), nullable=False)
    # 첫 릴리즈는 항상 NULL. 마이그레이션 없이 후추가가 불가능하므로 컬럼만 선반영한다.
    photo_s3_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # meal_items 합계의 캐시. 단일 진실은 meal_items.
    total_kcal: Mapped[int] = mapped_column(Integer, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    items: Mapped[list["MealItem"]] = relationship(back_populates="meal_log")


class MealItem(Base):
    __tablename__ = "meal_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    meal_log_id: Mapped[int] = mapped_column(ForeignKey("meal_logs.id"), index=True, nullable=False)
    food_label: Mapped[str] = mapped_column(String(100), nullable=False)
    serving_ratio: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    kcal: Mapped[int] = mapped_column(Integer, nullable=False)
    # ai / manual. 모델 개선의 근거가 된다.
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    # source='ai'일 때 YOLO score. (5,4) — 0.9995 이상이 1.0으로 반올림되지 않게 소수 4자리 보존 (리비전 0009).
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)

    # ── 기록 시점 영양 스냅샷 (리비전 0025) ─────────────────────────────────
    # **먹은 양 기준**(1인분 실측 × serving_ratio)이다. 실측이 없는 음식은 NULL.
    #
    # 왜 저장하는가: 이 값들이 없던 동안 하루 누적·경고는 매번 `food_label`로 `food_nutrition`을
    # 다시 조회해 계산했다. 그러면 **DB 값이 바뀔 때 과거 기록의 수치도 소급해 바뀐다** —
    # 기록이 아니라 추정이 된다. 2026-07-25에 1인분 기준을 4,536행 고쳤고 동명 행 규칙도
    # 바꿨는데, 그 순간 사용자의 지난 기록이 말하는 나트륨도 조용히 달라졌다.
    #
    # "판단에 쓸 근거를 정확하게 남긴다"(`docs/PRODUCT_STRATEGY.md` §0-1)는 목표에서
    # 근거는 **기록된 시점의 것**이어야 한다. 진료에서 되짚을 수 있으려면 더욱 그렇다.
    sodium_mg: Mapped[Decimal | None] = mapped_column(Numeric(8, 1), nullable=True)
    potassium_mg: Mapped[Decimal | None] = mapped_column(Numeric(8, 1), nullable=True)
    phosphorus_mg: Mapped[Decimal | None] = mapped_column(Numeric(8, 1), nullable=True)
    sugar_g: Mapped[Decimal | None] = mapped_column(Numeric(6, 1), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    meal_log: Mapped["MealLog"] = relationship(back_populates="items")


class WeightLog(Base):
    __tablename__ = "weight_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FoodNutrition(Base):
    __tablename__ = "food_nutrition"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # 조회 키. 같은 라벨 재요청은 캐시에서 돌려줘 HF 토큰 소비를 막는다.
    food_label: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    kcal_per_serving: Mapped[int] = mapped_column(Integer, nullable=False)
    serving_desc: Mapped[str] = mapped_column(String(100), nullable=False)
    # 1인분(= serving_desc가 가리키는 1회 제공량)이 몇 g인가. ml은 밀도≈1로 g 취급.
    # 앱이 사용자 입력 g ÷ serving_size_g 로 kcal 을 재환산한다. 원물 등 1회 제공량 미상은 NULL (리비전 0019).
    serving_size_g: Mapped[Decimal | None] = mapped_column(Numeric(6, 1), nullable=True)
    carbs_g: Mapped[Decimal | None] = mapped_column(Numeric(6, 1), nullable=True)
    protein_g: Mapped[Decimal | None] = mapped_column(Numeric(6, 1), nullable=True)
    fat_g: Mapped[Decimal | None] = mapped_column(Numeric(6, 1), nullable=True)
    # 아래 5개는 식약처(mfds) 임포트 전용 실측값. llm 행은 NULL (리비전 0007, DATA_MODEL.md 12장).
    sugar_g: Mapped[Decimal | None] = mapped_column(Numeric(6, 1), nullable=True)
    sodium_mg: Mapped[Decimal | None] = mapped_column(Numeric(8, 1), nullable=True)
    potassium_mg: Mapped[Decimal | None] = mapped_column(Numeric(8, 1), nullable=True)
    phosphorus_mg: Mapped[Decimal | None] = mapped_column(Numeric(8, 1), nullable=True)
    # 원본 식품대분류명. 추천 후보 풀이 meal_type 매핑에 쓴다.
    food_group: Mapped[str | None] = mapped_column(String(30), index=True, nullable=True)
    # llm / mfds / curated.
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ExerciseLog(Base):
    """운동 기록 — 식단(MealLog)과 같은 성격의 날마다 쌓이는 기록 (리비전 0020).

    하루 여러 건, soft delete, 하루 경계는 UTC 자정 — 끼니 기록의 관례를 그대로 따른다.
    `source` 는 지금 전부 'manual' 이지만, 기기 연동(3단계)이 같은 테이블에 들어오도록 미리 둔다
    (docs/ACTIVITY_GUIDANCE.md 3-2·3-3).
    """

    __tablename__ = "exercise_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    # 끼니 logged_at 과 같은 규약 — 과거 날짜 기록은 그 날의 UTC 정오로 앵커한다.
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exercise_type: Mapped[str] = mapped_column(String(30), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    # 보건복지부 지침의 강도 축과 일치 — light / moderate / vigorous.
    intensity: Mapped[str] = mapped_column(String(10), nullable=False)
    # MET 산출값 또는 사용자 입력. 체중을 모르면 산출할 수 없어 nullable.
    kcal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # manual / healthkit / health_connect.
    source: Mapped[str] = mapped_column(String(20), nullable=False, server_default="manual")
    memo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ExerciseGoal(Base):
    """개인 주간 운동 목표 (리비전 0021).

    기록(ExerciseLog)과 분리한다 — 목표가 바뀌어도 기록은 불변이다.
    UserGoal 과 같은 이력 구조: 열린 목표는 ended_at IS NULL 하나뿐이고 변경 시 이전 행을 닫는다.
    행이 없으면 지침 권장량(주 150분·근력 2일)이 기본값이다.
    """

    __tablename__ = "exercise_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    # 중강도 환산 분 (고강도는 2배로 환산해 비교한다).
    weekly_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    weekly_strength_days: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LabResult(Base):
    """검사 수치 — 케어 루프의 결과 축 (리비전 0027, `docs/CARE_LOOP.md` §4).

    식단만 기록하면 "나트륨을 얼마나 먹었다"까지만 말할 수 있다. 그래서 무엇이 달라졌는지는
    말하지 못했고, 목표(`docs/PRODUCT_STRATEGY.md` §0-2)의 "검사 수치가 나빠졌을 때 되짚을 수
    있었는가"가 반쪽이었다. 이 테이블이 그 나머지 절반이다.

    **우리가 측정하지 않는다.** 사용자가 결과지를 보고 옮겨 적거나 가정용 혈압계 값을 넣는다.
    Apple 은 "기기 센서만으로 혈압·혈당을 측정한다"고 주장하는 앱을 거부한다
    (`docs/LEGAL_COMPLIANCE.md` §6-1) — 우리 문구가 '측정'으로 읽히면 안 된다.

    항목·단위·정상범위는 `services/lab_panels.py` 가 단일 진실이다. DB 에 enum 을 두지 않는
    이유는 그것이 참조 데이터가 아니라 **지침 인용**이기 때문이다 — 지침이 개정되면 코드를
    고치지 마이그레이션을 돌릴 일이 아니다.
    """

    __tablename__ = "lab_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    # 검사일이지 입력일이 아니다. 지난 결과지를 나중에 옮겨 적는 것이 정상 흐름이다.
    measured_on: Mapped[date] = mapped_column(Date, nullable=False)
    panel: Mapped[str] = mapped_column(String(30), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False, server_default="manual")
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
