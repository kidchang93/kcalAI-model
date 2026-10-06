from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from crypto import EncryptedString
from database import Base, CreatedAt, UpdatedAt


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # 카카오 회원번호. 카카오 회원의 로그인 식별자다 (동의 없이 항상 제공되는 값).
    kakao_id: Mapped[str | None] = mapped_column(
        String(32), unique=True, index=True, nullable=True
    )
    # Apple 사용자 식별자(identity token 의 `sub`). Apple 회원의 로그인 식별자다 (리비전 0029).
    # 카카오 회원과 병합하지 않는다 — 같은 사람이라도 별개 회원이다.
    apple_sub: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    # 탈퇴 때 Apple 에 폐기(revoke)를 요청하는 데만 쓴다. 자격증명이라 암호화한다. deferred 인
    # 이유: 회원 행은 매 요청 인증마다 읽히는데, 그때마다 자격증명을 복호화할 이유가 없다.
    apple_refresh_token: Mapped[str | None] = mapped_column(
        EncryptedString(1024), nullable=True, deferred=True
    )
    # 이메일 회원의 로그인 식별자 (리비전 0030). 소문자로 정규화해 저장한다. 카카오·Apple 회원은
    # NULL 이다 — 그쪽은 이메일을 요청하지도 받지도 않는다. 다른 수단의 회원과 병합하지 않는다.
    email: Mapped[str | None] = mapped_column(String(254), unique=True, index=True, nullable=True)
    # scrypt 해시(`scrypt$n$r$p$salt$hash`). 원문은 어디에도 남기지 않는다. deferred 인 이유는
    # apple_refresh_token 과 같다 — 매 요청 인증마다 자격증명을 읽을 이유가 없다.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True, deferred=True)
    # 비밀번호 대입 방어. 연속 실패가 한도에 닿으면 잠그고, 성공·재설정 때 0 으로 되돌린다.
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    login_locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 카카오 닉네임·Apple 이름·이메일 가입 때 정한 닉네임. 그룹에서 다른 멤버에게 보이는 이름이다
    # (예전엔 마스킹한 휴대폰 번호였다). 카카오 프로필 동의를 거부하면 빈 값일 수 있어 nullable.
    nickname: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 휴대폰 인증(SMS)을 걷어내면서 식별자 자리를 잃었다. 컬럼은 남긴다 — 비즈 앱 전환 후
    # 전화번호 동의항목을 받게 되면 다시 채울 자리이고, 기존 행의 값을 지우지 않기 위해서다.
    phone_number: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    is_phone_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

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
    created_at: Mapped[CreatedAt]


class EmailVerificationCode(Base):
    """이메일로 보낸 6자리 인증 코드 — 가입(`signup`)과 비밀번호 재설정(`reset`).

    회원이 아직 없을 수 있어(가입) FK 없이 **이메일로 귀속**한다 — 탈퇴 연쇄는 이메일 기준으로
    지운다(kakao_link_codes 와 같은 규칙). 6자리는 대입 가능한 크기라 pepper 를 넣은 HMAC 으로만
    저장하고, 틀린 횟수를 세어 한도를 넘으면 그 코드를 버린다.

    이미 가입된 이메일로 가입 코드를 요청해도, 가입되지 않은 이메일로 재설정 코드를 요청해도
    **행은 똑같이 쌓인다**(보내는 메일만 다르다). 응답·재요청 제한이 같아야 이메일의 가입 여부가
    새지 않는다 — 만성질환 앱에 가입했다는 사실 자체가 건강 정보다.
    """

    __tablename__ = "email_verification_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(254), index=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 재요청 간격·하루 한도를 이 값으로 센다. 서비스가 앱 시계로 직접 채운다 — DB now() 는
    # 트랜잭션 시작 시각이라 만료(앱 시계)와 기준이 갈린다.
    created_at: Mapped[CreatedAt] = mapped_column(index=True)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[CreatedAt]

    user: Mapped[User] = relationship(back_populates="sessions")
