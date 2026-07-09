import hashlib
import os
import re
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.auth_model import AuthSession, PhoneVerificationCode, User


CODE_TTL_MINUTES = int(os.getenv("AUTH_CODE_TTL_MINUTES", "5"))
SESSION_TTL_DAYS = int(os.getenv("AUTH_SESSION_TTL_DAYS", "30"))
AUTH_CODE_PEPPER = os.getenv("AUTH_CODE_PEPPER", "development-only-pepper")
AUTH_INCLUDE_DEV_CODE = os.getenv("AUTH_INCLUDE_DEV_CODE", "true").lower() == "true"


def normalize_phone_number(phone_number: str) -> str:
    digits = re.sub(r"\D", "", phone_number)

    if digits.startswith("82") and len(digits) >= 11:
        digits = "0" + digits[2:]

    if len(digits) < 10 or len(digits) > 15:
        raise ValueError("휴대폰 번호 형식이 올바르지 않습니다.")

    return digits


def create_signup_code(db: Session, phone_number: str) -> tuple[datetime, str | None]:
    normalized_phone = normalize_phone_number(phone_number)
    user = _get_user_by_phone(db, normalized_phone)

    if user:
        raise ValueError("이미 가입된 휴대폰 번호입니다. 로그인으로 진행해주세요.")

    return _create_phone_code(db, normalized_phone, "signup")


def create_login_code(db: Session, phone_number: str) -> tuple[datetime, str | None]:
    normalized_phone = normalize_phone_number(phone_number)
    user = _get_user_by_phone(db, normalized_phone)

    if not user:
        raise ValueError("가입되지 않은 휴대폰 번호입니다. 회원가입을 먼저 진행해주세요.")

    return _create_phone_code(db, normalized_phone, "login")


def verify_signup_code(db: Session, phone_number: str, code: str) -> tuple[User, AuthSession]:
    normalized_phone = normalize_phone_number(phone_number)

    if _get_user_by_phone(db, normalized_phone):
        raise ValueError("이미 가입된 휴대폰 번호입니다. 로그인으로 진행해주세요.")

    _consume_valid_code(db, normalized_phone, code, "signup")
    user = User(phone_number=normalized_phone, is_phone_verified=True)
    db.add(user)
    db.flush()

    session = _create_session(user.id)
    db.add(session)
    db.commit()
    db.refresh(user)
    db.refresh(session)
    return user, session


def verify_login_code(db: Session, phone_number: str, code: str) -> tuple[User, AuthSession]:
    normalized_phone = normalize_phone_number(phone_number)
    user = _get_user_by_phone(db, normalized_phone)

    if not user:
        raise ValueError("가입되지 않은 휴대폰 번호입니다. 회원가입을 먼저 진행해주세요.")

    _consume_valid_code(db, normalized_phone, code, "login")
    session = _create_session(user.id)
    db.add(session)
    db.commit()
    db.refresh(user)
    db.refresh(session)
    return user, session


def get_user_by_session_token(db: Session, token: str) -> User | None:
    now = datetime.now(UTC)
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.token == token,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
    )

    if not session:
        return None

    return session.user


def revoke_session_token(db: Session, token: str) -> None:
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.token == token,
            AuthSession.revoked_at.is_(None),
        )
    )

    # 이미 폐기됐거나 없는 토큰이면 조용히 통과한다 (로그아웃은 멱등).
    if not session:
        return

    session.revoked_at = datetime.now(UTC)
    db.commit()


def _get_user_by_phone(db: Session, phone_number: str) -> User | None:
    return db.scalar(select(User).where(User.phone_number == phone_number))


def _create_phone_code(db: Session, phone_number: str, purpose: str) -> tuple[datetime, str | None]:
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = datetime.now(UTC) + timedelta(minutes=CODE_TTL_MINUTES)

    db.add(
        PhoneVerificationCode(
            phone_number=phone_number,
            purpose=purpose,
            code_hash=_hash_code(phone_number, purpose, code),
            expires_at=expires_at,
        )
    )
    db.commit()

    return expires_at, code if AUTH_INCLUDE_DEV_CODE else None


def _consume_valid_code(db: Session, phone_number: str, code: str, purpose: str) -> None:
    now = datetime.now(UTC)
    code_hash = _hash_code(phone_number, purpose, code)
    verification_code = db.scalar(
        select(PhoneVerificationCode)
        .where(
            PhoneVerificationCode.phone_number == phone_number,
            PhoneVerificationCode.purpose == purpose,
            PhoneVerificationCode.code_hash == code_hash,
            PhoneVerificationCode.consumed_at.is_(None),
            PhoneVerificationCode.expires_at > now,
        )
        .order_by(PhoneVerificationCode.created_at.desc())
    )

    if not verification_code:
        raise ValueError("인증번호가 올바르지 않거나 만료되었습니다.")

    verification_code.consumed_at = now
    db.flush()


def _create_session(user_id: int) -> AuthSession:
    return AuthSession(
        user_id=user_id,
        token=secrets.token_urlsafe(48),
        expires_at=datetime.now(UTC) + timedelta(days=SESSION_TTL_DAYS),
    )


def _hash_code(phone_number: str, purpose: str, code: str) -> str:
    raw = f"{AUTH_CODE_PEPPER}:{phone_number}:{purpose}:{code}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
