import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta

from timeutil import UTC

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from models.auth_model import AuthSession, PhoneVerificationCode, User


CODE_TTL_MINUTES = int(os.getenv("AUTH_CODE_TTL_MINUTES", "5"))
SESSION_TTL_DAYS = int(os.getenv("AUTH_SESSION_TTL_DAYS", "30"))
AUTH_CODE_PEPPER = os.getenv("AUTH_CODE_PEPPER", "development-only-pepper")
AUTH_INCLUDE_DEV_CODE = os.getenv("AUTH_INCLUDE_DEV_CODE", "true").lower() == "true"

# OTP 브루트포스 방어: 검증 실패가 이 횟수를 초과하면 코드를 무효화한다.
MAX_CODE_ATTEMPTS = 5
# request-code 남용 방지: 같은 번호의 재요청 쿨다운(초)과 시간당 발급 한도.
REQUEST_CODE_COOLDOWN_SECONDS = 60
REQUEST_CODE_HOURLY_LIMIT = 5

# 한국 휴대폰만 허용 (010/011/016/017/018/019 + 7~8자리). 유선번호(02...)는 거부한다.
_MOBILE_PHONE_PATTERN = re.compile(r"01[016789]\d{7,8}")

# 운영 배포를 막아야 하는 pepper 값 (미설정 기본값과 .env.example 플레이스홀더).
_INSECURE_PEPPERS = {"", "development-only-pepper", "change-this-local-secret"}


class RateLimitError(Exception):
    """인증번호 발급 빈도 초과. api 레이어가 429로 변환한다."""


def ensure_production_auth_config() -> None:
    # APP_ENV=production 기동 시 main.py가 호출한다. 개발 기본값을 그대로 배포하는 사고 방지.
    if AUTH_CODE_PEPPER in _INSECURE_PEPPERS:
        raise RuntimeError(
            "APP_ENV=production에서는 AUTH_CODE_PEPPER를 고유한 비밀값으로 설정해야 합니다."
        )

    if AUTH_INCLUDE_DEV_CODE:
        raise RuntimeError(
            "APP_ENV=production에서는 AUTH_INCLUDE_DEV_CODE=false로 설정해야 합니다."
        )


def normalize_phone_number(phone_number: str) -> str:
    digits = re.sub(r"\D", "", phone_number)

    if digits.startswith("82") and len(digits) >= 11:
        digits = "0" + digits[2:]

    if not _MOBILE_PHONE_PATTERN.fullmatch(digits):
        raise ValueError("휴대폰 번호 형식이 올바르지 않습니다. 010으로 시작하는 휴대폰 번호를 입력해주세요.")

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


def verify_signup_code(db: Session, phone_number: str, code: str) -> tuple[User, AuthSession, str]:
    normalized_phone = normalize_phone_number(phone_number)

    if _get_user_by_phone(db, normalized_phone):
        raise ValueError("이미 가입된 휴대폰 번호입니다. 로그인으로 진행해주세요.")

    _consume_valid_code(db, normalized_phone, code, "signup")
    user = User(phone_number=normalized_phone, is_phone_verified=True)
    db.add(user)
    db.flush()

    session, raw_token = _create_session(user.id)
    db.add(session)
    db.commit()
    db.refresh(user)
    db.refresh(session)
    return user, session, raw_token


def verify_login_code(db: Session, phone_number: str, code: str) -> tuple[User, AuthSession, str]:
    normalized_phone = normalize_phone_number(phone_number)
    user = _get_user_by_phone(db, normalized_phone)

    if not user:
        raise ValueError("가입되지 않은 휴대폰 번호입니다. 회원가입을 먼저 진행해주세요.")

    _consume_valid_code(db, normalized_phone, code, "login")
    session, raw_token = _create_session(user.id)
    db.add(session)
    db.commit()
    db.refresh(user)
    db.refresh(session)
    return user, session, raw_token


def get_user_by_session_token(db: Session, token: str) -> User | None:
    now = datetime.now(UTC)
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.token == _hash_session_token(token),
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
            AuthSession.token == _hash_session_token(token),
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
    now = datetime.now(UTC)
    _enforce_request_rate_limit(db, phone_number, now)

    # 단일 유효 코드 보장: 같은 번호·목적의 기존 미소비 코드를 전부 무효화한다.
    db.execute(
        update(PhoneVerificationCode)
        .where(
            PhoneVerificationCode.phone_number == phone_number,
            PhoneVerificationCode.purpose == purpose,
            PhoneVerificationCode.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )

    code = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = now + timedelta(minutes=CODE_TTL_MINUTES)

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


def _enforce_request_rate_limit(db: Session, phone_number: str, now: datetime) -> None:
    latest_created_at = db.scalar(
        select(func.max(PhoneVerificationCode.created_at)).where(
            PhoneVerificationCode.phone_number == phone_number
        )
    )

    if (
        latest_created_at is not None
        and (now - latest_created_at).total_seconds() < REQUEST_CODE_COOLDOWN_SECONDS
    ):
        raise RateLimitError("인증번호를 방금 발급했습니다. 60초 후에 다시 요청해주세요.")

    hourly_count = db.scalar(
        select(func.count())
        .select_from(PhoneVerificationCode)
        .where(
            PhoneVerificationCode.phone_number == phone_number,
            PhoneVerificationCode.created_at > now - timedelta(hours=1),
        )
    )

    if hourly_count >= REQUEST_CODE_HOURLY_LIMIT:
        raise RateLimitError("인증번호 요청이 너무 많습니다. 1시간 후에 다시 시도해주세요.")


def _consume_valid_code(db: Session, phone_number: str, code: str, purpose: str) -> None:
    now = datetime.now(UTC)
    verification_code = db.scalar(
        select(PhoneVerificationCode)
        .where(
            PhoneVerificationCode.phone_number == phone_number,
            PhoneVerificationCode.purpose == purpose,
            PhoneVerificationCode.consumed_at.is_(None),
            PhoneVerificationCode.expires_at > now,
        )
        .order_by(PhoneVerificationCode.created_at.desc())
        .limit(1)
    )

    if not verification_code:
        raise ValueError("인증번호가 올바르지 않거나 만료되었습니다.")

    submitted_hash = _hash_code(phone_number, purpose, code)

    if not secrets.compare_digest(verification_code.code_hash, submitted_hash):
        verification_code.attempt_count += 1

        # 브루트포스 방어: 실패가 한도를 초과하면 코드를 무효화한다.
        if verification_code.attempt_count > MAX_CODE_ATTEMPTS:
            verification_code.consumed_at = now

        # 실패 카운트는 이어지는 예외로 롤백되면 안 되므로 여기서 커밋한다.
        db.commit()
        raise ValueError("인증번호가 올바르지 않거나 만료되었습니다.")

    verification_code.consumed_at = now
    db.flush()


def _create_session(user_id: int) -> tuple[AuthSession, str]:
    # DB에는 해시만 저장하고 원문은 발급 응답에서만 반환한다 (DB 유출 시 재사용 방지).
    raw_token = secrets.token_urlsafe(48)
    session = AuthSession(
        user_id=user_id,
        token=_hash_session_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(days=SESSION_TTL_DAYS),
    )
    return session, raw_token


def _hash_code(phone_number: str, purpose: str, code: str) -> str:
    raw = f"{AUTH_CODE_PEPPER}:{phone_number}:{purpose}:{code}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _hash_session_token(token: str) -> str:
    # 토큰 자체가 384비트 난수라 pepper 없이 단순 sha256으로 충분하다.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# 정기 정리 배치 보존창.
# 코드: 발급 1일 뒤 삭제 — TTL 5분·레이트리밋 1시간창을 넉넉히 지난 뒤라 카운트에 영향 없음.
# 세션: 만료·폐기 7일 뒤 삭제 (짧은 감사 유예).
CODE_RETENTION_DAYS = 1
SESSION_RETENTION_DAYS = 7


def purge_expired_auth(db: Session) -> dict[str, int]:
    """만료된 인증코드와 만료·폐기된 세션을 물리 삭제한다. 정기 배치용(멱등).

    반환: 삭제 건수 `{"codes": n, "sessions": m}`.
    """
    now = datetime.now(UTC)

    codes_deleted = db.execute(
        delete(PhoneVerificationCode).where(
            PhoneVerificationCode.created_at < now - timedelta(days=CODE_RETENTION_DAYS)
        )
    ).rowcount

    sessions_deleted = db.execute(
        delete(AuthSession).where(
            or_(
                AuthSession.expires_at < now - timedelta(days=SESSION_RETENTION_DAYS),
                AuthSession.revoked_at < now - timedelta(days=SESSION_RETENTION_DAYS),
            )
        )
    ).rowcount

    db.commit()
    return {"codes": codes_deleted, "sessions": sessions_deleted}
