from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # family / couple / friends / challenge
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # 서버가 생성하는 참여 코드. 클라이언트가 지정할 수 없다.
    invite_code: Mapped[str] = mapped_column(String(12), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GroupMember(Base):
    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    # owner / member
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GroupPet(Base):
    __tablename__ = "group_pets"
    __table_args__ = (UniqueConstraint("group_id", "pet_id"),)

    # 사람 멤버(group_members)와 테이블을 분리한다 — 다형성 FK 를 피하기 위해서다 (DATA_MODEL.md 6장).
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True, nullable=False)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pets.id"), index=True, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GroupChallenge(Base):
    """그룹 운동 챌린지 (리비전 0022).

    exercise_logs 를 **집계만** 한다 — 기록은 챌린지를 모르고(외래키 없음), 챌린지가 삭제돼도
    기록은 그대로다. 순위에는 `group_activity_share` 동의를 한 멤버만 나타난다.
    """

    __tablename__ = "group_challenges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True, nullable=False)
    # 만든 사람이 탈퇴해도 챌린지는 남는다 — 삭제 연쇄가 NULL 로 끊는다.
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(60), nullable=False)
    # 1인당 목표(중강도 환산 분).
    target_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
