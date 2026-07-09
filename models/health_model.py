from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, func
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
    # source='ai'일 때 YOLO score.
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
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
    carbs_g: Mapped[Decimal | None] = mapped_column(Numeric(6, 1), nullable=True)
    protein_g: Mapped[Decimal | None] = mapped_column(Numeric(6, 1), nullable=True)
    fat_g: Mapped[Decimal | None] = mapped_column(Numeric(6, 1), nullable=True)
    # llm / curated.
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
