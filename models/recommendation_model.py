from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class DietRecommendation(Base):
    __tablename__ = "diet_recommendations"
    # 사용자·날짜·끼니당 1회 생성 (캐시 = 재현성 + 비용 통제, DATA_MODEL.md 11장).
    __table_args__ = (UniqueConstraint("user_id", "rec_date", "meal_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    # 클라이언트가 보낸 날짜. summary 와 동일하게 서버는 시간대 해석을 하지 않는다.
    rec_date: Mapped[date] = mapped_column(Date, nullable=False)
    meal_type: Mapped[str] = mapped_column(String(10), nullable=False)
    # [{"name": str, "kcal": int, "reason": str}] — kcal 은 식약처 실측 DB 값 (12장 개정).
    items: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    # 반영된 제외 조건 {type: allergen|condition, code, label}
    # + 후처리 필터로 실제 탈락한 후보 {type: filtered, name, matched_keyword}.
    excluded: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    # 13장부터 항상 rule (순수 규칙 선정). llm 은 12장 이전 생성분의 레거시 값.
    source: Mapped[str] = mapped_column(String(20), server_default="llm", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
