from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
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
