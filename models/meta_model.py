from sqlalchemy import Boolean, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ConditionType(Base):
    __tablename__ = "condition_types"

    code: Mapped[str] = mapped_column(String(30), primary_key=True)
    label_ko: Mapped[str] = mapped_column(String(50), nullable=False)
    # 추천 엔진 내부용 식이 규칙 태그. 메타 API 로 노출하지 않는다 (DATA_MODEL.md 10장).
    dietary_tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    # 기록 시 경고 판정용 (16장). 추천 후보 필터에는 쓰지 않는다 — 추천 동작 불변.
    exclude_keywords: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)


class AllergenType(Base):
    __tablename__ = "allergen_types"

    code: Mapped[str] = mapped_column(String(30), primary_key=True)
    label_ko: Mapped[str] = mapped_column(String(50), nullable=False)
    # 추천 엔진 내부용 제외 재료 키워드. 메타 API 로 노출하지 않는다 (DATA_MODEL.md 10장).
    exclude_keywords: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
