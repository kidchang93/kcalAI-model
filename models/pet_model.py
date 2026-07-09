from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Pet(Base):
    __tablename__ = "pets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # 보호자 1 : N. 반려동물은 로그인하지 않는 독립 엔티티다 (DATA_MODEL.md 6장).
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    # dog / cat / other
    species: Mapped[str] = mapped_column(String(10), nullable=False)
    breed: Mapped[str | None] = mapped_column(String(50), nullable=True)
    birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 1), nullable=True)
    # 모름 허용이라 nullable.
    is_neutered: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
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


class PetFeedingLog(Base):
    __tablename__ = "pet_feeding_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pets.id"), index=True, nullable=False)
    fed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
    food_label: Mapped[str] = mapped_column(String(100), nullable=False)
    amount_g: Mapped[Decimal] = mapped_column(Numeric(6, 1), nullable=False)
    # MVP 는 급여량(g)만 기록한다. 칼로리 산출(RER/MER)은 다음 단계 (DATA_MODEL.md 6장).
    kcal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
