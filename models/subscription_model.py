from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Plan(Base):
    """요금제 참조 테이블 (DATA_MODEL.md 10장 규칙 — 릴리즈 없이 가격·한도를 조정한다)."""

    __tablename__ = "plans"

    # lite / pro / premium
    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    label_ko: Mapped[str] = mapped_column(String(30), nullable=False)
    # 0 = 무료(lite). 표시용이며 결제 연동 전까지 과금에 쓰이지 않는다.
    price_krw: Mapped[int] = mapped_column(Integer, nullable=False)
    # 비전 LLM(/api/predict) 일일 호출 상한. KST 자정 리셋.
    daily_vision_quota: Mapped[int] = mapped_column(Integer, nullable=False)
    # 내가 만든 그룹에 "본인 말고" 추가할 수 있는 인원. 정원 = 이 값 + 1(owner).
    max_group_members: Mapped[int] = mapped_column(Integer, nullable=False)
    max_pets: Mapped[int] = mapped_column(Integer, nullable=False)
    # 그룹을 여러 개 만들어 인원 제한을 우회하는 것을 막는다.
    max_owned_groups: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)


class UserSubscription(Base):
    """회원 1 : 요금제 1. user_id 를 PK 로 두어 1:1을 스키마로 강제한다."""

    __tablename__ = "user_subscriptions"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    plan_code: Mapped[str] = mapped_column(ForeignKey("plans.code"), index=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class VisionUsageDaily(Base):
    """비전 LLM 일일 사용량 카운터 (user_id + KST 날짜).

    호출 로그를 COUNT 하지 않고 카운터 행을 두는 이유는, 한도 판정과 증가를 한 문장의
    UPSERT 로 원자화하기 위해서다 (동시 요청이 한도를 넘겨 통과하는 경합을 막는다).
    """

    __tablename__ = "vision_usage_daily"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    # KST 기준 날짜. UTC 로 저장하면 한국 사용자의 자정 리셋 체감과 9시간 어긋난다.
    usage_date: Mapped[date] = mapped_column(Date, primary_key=True)
    used_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
