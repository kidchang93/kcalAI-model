from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # 카카오 회원번호. 유일한 로그인 식별자다 (동의 없이 항상 제공되는 값).
    kakao_id: Mapped[str | None] = mapped_column(
        String(32), unique=True, index=True, nullable=True
    )
    # 카카오 닉네임. 그룹에서 다른 멤버에게 보이는 이름이다 (예전엔 마스킹한 휴대폰 번호였다).
    # 사용자가 프로필 동의를 거부하면 빈 값일 수 있어 nullable.
    nickname: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 휴대폰 인증(SMS)을 걷어내면서 식별자 자리를 잃었다. 컬럼은 남긴다 — 비즈 앱 전환 후
    # 전화번호 동의항목을 받게 되면 다시 채울 자리이고, 기존 행의 값을 지우지 않기 위해서다.
    phone_number: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    is_phone_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    sessions: Mapped[list["AuthSession"]] = relationship(back_populates="user")


class KakaoLinkCode(Base):
    """카카오 콜백 → 앱으로 건네는 **1회용** 연동 코드.

    카카오 인가 코드는 1회용이라, 콜백에서 교환한 결과를 앱이 다시 쓸 수 없다. 그런데 신규
    회원은 약관 동의·요금제 선택을 거쳐야 가입이 완료된다. 그래서 콜백이 회원번호·닉네임을
    이 행에 담아두고, 앱은 딥링크로 받은 코드로 로그인 또는 가입을 마무리한다.

    세션 토큰과 같은 규칙으로 **해시만 저장**한다 (딥링크 URL·로그에 원문이 남더라도 DB 유출과
    조합되지 않게).
    """

    __tablename__ = "kakao_link_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    kakao_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(50), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped[User] = relationship(back_populates="sessions")
