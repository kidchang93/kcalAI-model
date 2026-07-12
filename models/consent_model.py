from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from crypto import EncryptedString
from database import Base


class UserConsent(Base):
    __tablename__ = "user_consents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    # sensitive_health / terms / privacy
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # 약관 버전. 나중에 약관이 바뀌었을 때 누가 무엇에 동의했는지 증명하는 근거다.
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    agreed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 철회 증빙. 재동의는 새 행을 만든다 (이력 보존).
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserHealthProfile(Base):
    __tablename__ = "user_health_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    # A / B / O / AB / unknown. 모름 허용이라 nullable. 민감정보라 암호화 저장.
    blood_type: Mapped[str | None] = mapped_column(EncryptedString(255), nullable=True)
    # + / -. 민감정보라 암호화 저장.
    rh: Mapped[str | None] = mapped_column(EncryptedString(255), nullable=True)
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


class UserCondition(Base):
    __tablename__ = "user_conditions"
    __table_args__ = (UniqueConstraint("user_id", "condition"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    # diabetes / pregnancy / ckd / cancer / hypertension. 참조 테이블(condition_types) FK·JOIN·
    # 추천/경고 필터에 쓰이는 기능 키라 암호화하지 않는다 (평문 코드 유지).
    condition: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UserAllergy(Base):
    __tablename__ = "user_allergies"
    __table_args__ = (UniqueConstraint("user_id", "allergen"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    # 참조 테이블(allergen_types) FK·JOIN·추천/경고 필터에 쓰이는 기능 키라 암호화하지 않는다.
    allergen: Mapped[str] = mapped_column(String(100), nullable=False)
    # mild / severe
    severity: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
