"""인증 — 카카오 로그인 + Sign in with Apple(iOS).

SMS(휴대폰 OTP)는 2026-07-14에 제거했다. 카카오가 웹·Android 의 유일한 수단이므로, 카카오 설정이
없으면 그쪽은 아무도 로그인하지 못한다 (`ensure_production_kakao_config`). Apple 은 App Store
심사 4.8(소셜 로그인만 있으면 대안 필수) 때문에 2026-10-05 에 붙였다.

카카오 흐름 (DATA_MODEL.md 21장):
  앱 → GET /api/auth/kakao/start        (서버가 state 서명 후 카카오로 302)
  카카오 → GET /api/auth/kakao/callback (서버가 코드 교환·프로필 조회 → **1회용 연동 코드** 발급)
  서버 → 앱 딥링크 (kcalairn://auth?code=...&is_new=true|false)
  앱 → POST /api/auth/kakao/login  또는  /api/auth/kakao/signup (연동 코드 → 세션 토큰)

Apple 흐름 — 서버 주도 OAuth 가 아니다. iOS 가 기기에서 identity token 을 받아 앱이 보낸다:
  앱 → POST /api/auth/apple/login  {identity_token}                       (미가입 404)
  앱 → POST /api/auth/apple/signup {identity_token, authorization_code, ...}
연동 코드 테이블이 없다 — 동의 화면 동안 토큰을 들고 있는 쪽이 앱이다 (identity token 10분).

이메일 흐름 (2026-10-06) — 카카오·Apple 계정이 없는 사람의 가입 수단. 이메일은 6자리 코드로 확인한다:
  앱 → POST /api/auth/email/signup/code   {email}            (코드 메일 — 이미 회원이면 안내 메일)
  앱 → POST /api/auth/email/signup/verify {email, code}      (확인만, 소비하지 않는다)
  앱 → POST /api/auth/email/signup/nickname {email, code, nickname}  (닉네임 중복확인 — 코드가 있어야 한다)
  앱 → POST /api/auth/email/signup        {email, code, password, nickname, 동의...}
  앱 → POST /api/auth/email/login         {email, password}
  앱 → POST /api/auth/email/password-reset/code {email}  →  /password-reset {email, code, new_password}
코드 요청의 응답은 이메일의 가입 여부와 무관하게 같다 — `EmailVerificationCode` 주석.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime, timedelta
from functools import cache

from timeutil import UTC

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from log_utils import get_logger
from models.auth_model import AuthSession, EmailVerificationCode, KakaoLinkCode, User
from services import apple_client, mail_client
from services.errors import BadRequestError, NotFoundError
from services.consent_service import PRIVACY, TERMS, ensure_current_version, record_signup_consents
from services.subscription_service import create_subscription


SESSION_TTL_DAYS = int(os.getenv("AUTH_SESSION_TTL_DAYS", "30"))
AUTH_CODE_PEPPER = os.getenv("AUTH_CODE_PEPPER", "development-only-pepper")

# 연동 코드는 콜백 직후 앱이 즉시 교환한다. 짧게 잡는다 (신규 회원의 동의·요금제 선택 시간 포함).
LINK_CODE_TTL_MINUTES = 10
# OAuth state 유효시간 — 사용자가 카카오 동의 화면에 머무는 시간.
STATE_TTL_MINUTES = 10

# 운영 배포를 막아야 하는 pepper 값 (미설정 기본값과 .env.example 플레이스홀더).
_INSECURE_PEPPERS = {"", "development-only-pepper", "change-this-local-secret"}

logger = get_logger(__name__)

# ---- 이메일 가입 한도 ----
EMAIL_SIGNUP = "signup"
EMAIL_RESET = "reset"
EMAIL_CODE_TTL_MINUTES = 10
# 6자리는 100만 가지라 틀린 횟수를 막지 않으면 대입된다. 넘으면 그 코드는 버리고 새로 받게 한다.
EMAIL_CODE_MAX_ATTEMPTS = 5
EMAIL_RESEND_SECONDS = 60
EMAIL_DAILY_PER_ADDRESS = 10
# 발송 계정 전체의 하루 한도. SMTP 제공자의 하루 발송 한도보다 낮게 둔다 — 남이 아무 주소로나
# 코드를 요청해 우리 계정을 스팸 발송자로 만들지 못하게 하는 마지막 방어선이다.
MAIL_DAILY_LIMIT = int(os.getenv("MAIL_DAILY_LIMIT", "300"))
# 비밀번호 대입 방어. 연속 실패가 한도에 닿으면 잠시 잠근다(재설정하면 풀린다).
LOGIN_MAX_FAILURES = 10
LOGIN_LOCK_MINUTES = 15
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 64
# scrypt 비용 — OWASP Password Storage Cheat Sheet 의 최소 권장(N=2^14 이면 r=8·p=5, 메모리 16MiB).
# 1건 약 0.1초라 로그인 한 번에는 체감이 없고, DB 가 털려도 비밀번호 대입이 그만큼 느려진다.
# bcrypt 보다 나은 이유: 메모리를 써서 GPU 대량 대입이 어렵고, 72바이트에서 잘리지 않고, stdlib 다.
# 올리면 기존 해시는 해시 문자열에 담긴 옛 값으로 계속 검증된다.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 5

_EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_PASSWORD_LETTER = re.compile(r"[A-Za-z]")
_PASSWORD_DIGIT = re.compile(r"[0-9]")

EMAIL_INVALID_MESSAGE = "이메일 주소를 확인해주세요."
PASSWORD_RULE_MESSAGE = "비밀번호는 영문과 숫자를 섞어 8~64자로 정해주세요."
CODE_EXPIRED_MESSAGE = "인증 코드가 만료됐어요. 코드를 다시 받아주세요."
CODE_WRONG_MESSAGE = "인증 코드가 맞지 않아요. 다시 확인해주세요."
NICKNAME_TAKEN_MESSAGE = "이미 쓰는 닉네임이에요. 다른 닉네임을 정해주세요."
# 실패 사유(없는 이메일·틀린 비밀번호·잠김)를 하나의 문구로 답한다 — 사유가 갈리면 그 이메일이
# 가입돼 있는지가 새어 나간다.
LOGIN_FAILED_MESSAGE = (
    "이메일 또는 비밀번호가 맞지 않아요. 여러 번 틀리면 15분 동안 로그인이 막히니, "
    "기억나지 않으면 비밀번호를 재설정해주세요."
)


class StateError(Exception):
    """OAuth state 위조·만료. api 레이어가 400으로 변환한다 (CSRF 방어)."""


class RateLimitError(Exception):
    """인증 메일 재요청이 너무 잦다. api 레이어가 429 로 바꾼다(기다리면 풀린다 — 402 와 다르다)."""


def ensure_production_auth_config() -> None:
    # APP_ENV=production 기동 시 main.py가 호출한다. 개발 기본값을 그대로 배포하는 사고 방지.
    # pepper는 세션·연동 코드 해시와 state 서명에 함께 쓰인다.
    if AUTH_CODE_PEPPER in _INSECURE_PEPPERS:
        raise RuntimeError(
            "APP_ENV=production에서는 AUTH_CODE_PEPPER를 고유한 비밀값으로 설정해야 합니다."
        )


# ---- OAuth state (CSRF) ----
# 서명한 값이라 별도 테이블이 필요 없다. 콜백이 우리가 시작시킨 요청인지, 어느 플랫폼으로
# 돌려보낼지를 여기에 담는다.

def create_state(platform: str) -> str:
    payload = {
        "platform": platform,
        "nonce": secrets.token_urlsafe(12),
        "exp": int((datetime.now(UTC) + timedelta(minutes=STATE_TTL_MINUTES)).timestamp()),
    }
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    return f"{raw}.{_sign(raw)}"


def verify_state(state: str) -> str:
    """서명·만료를 검증하고 platform 을 돌려준다."""
    raw, _, signature = state.partition(".")

    if not raw or not signature or not secrets.compare_digest(signature, _sign(raw)):
        raise StateError("로그인 요청이 유효하지 않습니다. 다시 시도해주세요.")

    payload = _decode_state_payload(raw)

    if payload is None:
        raise StateError("로그인 요청이 유효하지 않습니다. 다시 시도해주세요.")

    if int(payload.get("exp", 0)) < int(datetime.now(UTC).timestamp()):
        raise StateError("로그인 요청이 만료되었습니다. 다시 시도해주세요.")

    return str(payload.get("platform", "native"))


def platform_hint(state: str | None) -> str:
    """**검증하지 않고** platform 만 꺼낸다 — state 가 깨졌을 때 어디로 되돌릴지 정하는 용도다.

    서명이 깨졌다고 딥링크(`kcalairn://`)로 되돌리면, 웹 사용자는 브라우저가 그 스킴을 열 수
    없어 오류 화면에 갇힌다. 반대로 웹 경로로 되돌리면 앱의 인앱 브라우저가 닫히지 않는다.
    그래서 **에러 응답의 목적지**만 이 힌트로 고른다.

    보안상 안전하다: 이 값은 오류를 어디로 보낼지만 정하고, 세션이나 권한에는 관여하지 않는다.
    공격자가 조작해 봐야 자기가 받을 오류 화면의 종류만 바뀐다.
    """
    if not state:
        return "native"

    payload = _decode_state_payload(state.partition(".")[0])

    if payload is None or payload.get("platform") not in ("native", "web"):
        return "native"

    return str(payload["platform"])


def _decode_state_payload(raw: str) -> dict | None:
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")))
    except (ValueError, TypeError):
        return None

    return payload if isinstance(payload, dict) else None


# ---- 연동 코드 ----

def create_link_code(db: Session, kakao_id: str, nickname: str) -> tuple[str, bool]:
    """카카오 콜백이 부른다. `(원문 코드, 신규 회원 여부)`.

    같은 카카오 계정의 미소비 코드는 무효화한다 (단일 유효 코드 — OTP 때와 같은 규칙).
    """
    now = datetime.now(UTC)

    db.execute(
        delete(KakaoLinkCode).where(
            KakaoLinkCode.kakao_id == kakao_id,
            KakaoLinkCode.consumed_at.is_(None),
        )
    )

    raw_code = secrets.token_urlsafe(32)
    db.add(
        KakaoLinkCode(
            code_hash=_hash_token(raw_code),
            kakao_id=kakao_id,
            nickname=nickname or None,
            expires_at=now + timedelta(minutes=LINK_CODE_TTL_MINUTES),
        )
    )
    db.commit()

    is_new_user = _get_user_by_kakao_id(db, kakao_id) is None
    return raw_code, is_new_user


def _consume_link_code(db: Session, raw_code: str) -> KakaoLinkCode:
    now = datetime.now(UTC)
    link_code = db.scalar(
        select(KakaoLinkCode).where(
            KakaoLinkCode.code_hash == _hash_token(raw_code),
            KakaoLinkCode.consumed_at.is_(None),
            KakaoLinkCode.expires_at > now,
        )
    )

    if link_code is None:
        raise BadRequestError("로그인 정보가 만료되었습니다. 다시 시도해주세요.")

    link_code.consumed_at = now
    db.flush()
    return link_code


# ---- 로그인 · 가입 ----

def kakao_login(db: Session, raw_code: str) -> tuple[User, AuthSession, str]:
    link_code = _consume_link_code(db, raw_code)
    user = _get_user_by_kakao_id(db, link_code.kakao_id)

    if user is None:
        raise NotFoundError("가입되지 않은 카카오 계정입니다. 회원가입을 먼저 진행해주세요.")

    # 카카오에서 닉네임을 바꿨으면 따라간다 (그룹에 보이는 이름이다).
    if link_code.nickname and link_code.nickname != user.nickname:
        user.nickname = link_code.nickname

    return _start_session(db, user)


def kakao_signup(
    db: Session,
    raw_code: str,
    agreed_terms: bool,
    agreed_privacy: bool,
    plan_code: str | None = None,
    terms_version: str | None = None,
    privacy_version: str | None = None,
) -> tuple[User, AuthSession, str]:
    _ensure_signup_agreements(agreed_terms, agreed_privacy, terms_version, privacy_version)
    link_code = _consume_link_code(db, raw_code)

    if _get_user_by_kakao_id(db, link_code.kakao_id) is not None:
        raise BadRequestError("이미 가입된 카카오 계정입니다. 로그인으로 진행해주세요.")

    user = User(kakao_id=link_code.kakao_id, nickname=link_code.nickname)
    return _create_member(db, user, plan_code, terms_version, privacy_version)


def apple_login(db: Session, identity_token: str) -> tuple[User, AuthSession, str]:
    apple_sub = apple_client.verify_identity_token(identity_token)
    user = _get_user_by_apple_sub(db, apple_sub)

    if user is None:
        raise NotFoundError("가입되지 않은 Apple 계정입니다. 회원가입을 먼저 진행해주세요.")

    return _start_session(db, user)


def apple_signup(
    db: Session,
    identity_token: str,
    authorization_code: str,
    agreed_terms: bool,
    agreed_privacy: bool,
    nickname: str | None = None,
    terms_version: str | None = None,
    privacy_version: str | None = None,
    plan_code: str | None = None,
) -> tuple[User, AuthSession, str]:
    _ensure_signup_agreements(agreed_terms, agreed_privacy, terms_version, privacy_version)
    apple_sub = apple_client.verify_identity_token(identity_token)

    # 교환 전에 막는다 — 이미 회원이면 refresh token 을 새로 받을 이유가 없다.
    if _get_user_by_apple_sub(db, apple_sub) is not None:
        raise BadRequestError("이미 가입된 Apple 계정입니다. 로그인으로 진행해주세요.")

    # 회원 행보다 먼저다: 탈퇴 때 폐기할 토큰 없이 Apple 회원이 생기면 안 된다.
    refresh_token = apple_client.exchange_code(authorization_code)
    # 이름은 Apple 이 첫 로그인에만 준다(앱이 조합해 보낸다). 이메일은 요청하지도 받지도 않는다.
    user = User(
        apple_sub=apple_sub,
        nickname=(nickname or "").strip() or None,
        apple_refresh_token=refresh_token,
    )
    return _create_member(db, user, plan_code, terms_version, privacy_version)


# ---- 이메일 가입 ----

def request_email_code(db: Session, email: str, purpose: str) -> None:
    """가입·재설정 코드를 보낸다. 응답은 언제나 같다 — 메일 내용만 가입 여부에 따라 다르다.

    - 가입: 미가입이면 코드, 이미 회원이면 '이미 가입된 이메일' 안내(코드 없음).
    - 재설정: 이메일 회원이면 코드, 아니면 아무것도 보내지 않는다(모르는 주소로 메일을 쏘지 않는다).
    어느 쪽이든 코드 행은 쌓인다 — 재요청 제한이 같아야 429 로도 가입 여부가 새지 않는다.
    """
    email = normalize_email(email)
    now = datetime.now(UTC)
    _ensure_can_send(db, email, now)

    code = f"{secrets.randbelow(10**6):06d}"
    user = _get_user_by_email(db, email)
    # 메일로 나가지 않는 코드(이미 회원·미가입 재설정)는 아무도 모르는 값으로 저장한다 — 맞힐 수 없다.
    stored_code = code if (user is None) == (purpose == EMAIL_SIGNUP) else secrets.token_hex(16)
    db.add(
        EmailVerificationCode(
            email=email,
            purpose=purpose,
            code_hash=_hash_email_code(email, purpose, stored_code),
            expires_at=now + timedelta(minutes=EMAIL_CODE_TTL_MINUTES),
            created_at=now,
        )
    )
    db.flush()

    try:
        if purpose == EMAIL_SIGNUP and user is None:
            mail_client.send_mail(email, f"[케어테이블] 인증 코드 {code}", _signup_code_body(code))
        elif purpose == EMAIL_SIGNUP:
            mail_client.send_mail(email, "[케어테이블] 이미 가입된 이메일이에요", _already_registered_body())
        elif user is not None:
            mail_client.send_mail(email, f"[케어테이블] 비밀번호 재설정 코드 {code}", _reset_code_body(code))
    except mail_client.MailUnavailableError:
        # 보내지 못한 코드가 남으면 재요청이 1분 막힌다.
        db.rollback()
        raise

    db.commit()


def verify_signup_code(db: Session, email: str, code: str) -> None:
    """가입 코드가 맞는지만 본다(소비하지 않는다). 가입 폼을 다 채운 뒤에야 오타를 아는 일을 막는다."""
    email = normalize_email(email)
    _, error = _match_email_code(db, email, EMAIL_SIGNUP, code)
    db.commit()

    if error:
        raise BadRequestError(error)


def check_signup_nickname(db: Session, email: str, code: str, nickname: str) -> None:
    """가입 화면의 닉네임 중복확인. **확인된 가입 코드가 있어야** 물을 수 있다.

    아무나 부르는 '닉네임 있나요?' 는 그 닉네임(카카오 닉네임·Apple 실명인 경우가 많다)의 주인이
    이 만성질환 앱 회원인지를 알려 주는 통로가 된다. 그래서 메일함을 가진 사람만, '이미 있음'은
    코드 시도 횟수를 써 가며(코드당 5번) 물을 수 있게 한다.
    """
    email = normalize_email(email)
    nickname = _require_nickname(nickname)
    row, error = _match_email_code(db, email, EMAIL_SIGNUP, code)

    if error is None and _is_nickname_taken(db, nickname):
        row.attempt_count += 1
        error = NICKNAME_TAKEN_MESSAGE

    db.commit()

    if error:
        raise BadRequestError(error)


def email_signup(
    db: Session,
    email: str,
    code: str,
    password: str,
    nickname: str,
    agreed_terms: bool,
    agreed_privacy: bool,
    terms_version: str | None = None,
    privacy_version: str | None = None,
    plan_code: str | None = None,
) -> tuple[User, AuthSession, str]:
    _ensure_signup_agreements(agreed_terms, agreed_privacy, terms_version, privacy_version)
    email = normalize_email(email)
    _ensure_password_rule(password)
    nickname = _require_nickname(nickname)
    row, error = _match_email_code(db, email, EMAIL_SIGNUP, code)

    # 중복확인을 건너뛴 요청·확인 뒤 남이 먼저 가져간 경우. 중복확인과 같이 시도 횟수를 쓴다.
    if error is None and _is_nickname_taken(db, nickname):
        row.attempt_count += 1
        error = NICKNAME_TAKEN_MESSAGE

    if error:
        db.commit()  # 틀린 횟수는 남겨야 한다
        raise BadRequestError(error)

    # 이미 회원인 주소에는 코드가 나가지 않으므로 여기 오는 건 동시 가입뿐이다.
    if _get_user_by_email(db, email) is not None:
        raise BadRequestError("이미 가입된 이메일이에요. 로그인해주세요.")

    row.consumed_at = datetime.now(UTC)
    user = User(email=email, password_hash=_hash_password(password), nickname=nickname)
    return _create_member(db, user, plan_code, terms_version, privacy_version)


def email_login(db: Session, email: str, password: str) -> tuple[User, AuthSession, str]:
    email = normalize_email(email)
    now = datetime.now(UTC)
    user = _get_user_by_email(db, email)
    # 없는 이메일·잠긴 계정도 해시를 한 번 계산한다 — 응답 시간으로 가입 여부가 새지 않게.
    is_valid = _verify_password(password, user.password_hash if user else None)

    if user is None:
        raise BadRequestError(LOGIN_FAILED_MESSAGE)

    if user.login_locked_until is not None and user.login_locked_until > now:
        raise BadRequestError(LOGIN_FAILED_MESSAGE)

    if not is_valid:
        user.failed_login_count += 1

        if user.failed_login_count >= LOGIN_MAX_FAILURES:
            user.failed_login_count = 0
            user.login_locked_until = now + timedelta(minutes=LOGIN_LOCK_MINUTES)

        db.commit()
        raise BadRequestError(LOGIN_FAILED_MESSAGE)

    user.failed_login_count = 0
    user.login_locked_until = None
    return _start_session(db, user)


def reset_password(db: Session, email: str, code: str, new_password: str) -> None:
    """비밀번호를 바꾸고 **모든 세션을 끊는다** — 잃어버린 기기·탈취된 세션이 남아 있으면 안 된다."""
    email = normalize_email(email)
    _ensure_password_rule(new_password)
    row, error = _match_email_code(db, email, EMAIL_RESET, code)

    if error:
        db.commit()
        raise BadRequestError(error)

    user = _get_user_by_email(db, email)

    # 회원이 아니면 코드가 메일로 나가지 않았으므로 맞을 수 없다. 방어로만 둔다.
    if user is None:
        raise BadRequestError(CODE_EXPIRED_MESSAGE)

    now = datetime.now(UTC)
    row.consumed_at = now
    user.password_hash = _hash_password(new_password)
    user.failed_login_count = 0
    user.login_locked_until = None
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    db.commit()


def normalize_email(email: str) -> str:
    # 대소문자만 다른 주소가 서로 다른 회원이 되지 않게 전부 소문자로 둔다. 점·+태그는 제공자마다
    # 규칙이 달라 손대지 않는다.
    normalized = email.strip().lower()

    if len(normalized) > 254 or not _EMAIL_PATTERN.fullmatch(normalized):
        raise BadRequestError(EMAIL_INVALID_MESSAGE)

    return normalized


def _ensure_can_send(db: Session, email: str, now: datetime) -> None:
    latest = db.scalar(
        select(func.max(EmailVerificationCode.created_at)).where(EmailVerificationCode.email == email)
    )

    if latest is not None and latest > now - timedelta(seconds=EMAIL_RESEND_SECONDS):
        raise RateLimitError("인증 메일은 1분에 한 번 보낼 수 있어요. 잠시 후 다시 시도해주세요.")

    day_ago = now - timedelta(days=1)
    sent_to_address = db.scalar(
        select(func.count()).where(
            EmailVerificationCode.email == email, EmailVerificationCode.created_at > day_ago
        )
    )

    if sent_to_address >= EMAIL_DAILY_PER_ADDRESS:
        raise RateLimitError("오늘은 이 주소로 인증 메일을 더 보낼 수 없어요. 내일 다시 시도해주세요.")

    # ponytail: 전체 한도는 남이 소진하면 그날 이메일 가입이 막힌다. 실제로 일어나면 IP 단위 제한을 둔다.
    sent_total = db.scalar(select(func.count()).where(EmailVerificationCode.created_at > day_ago))

    if sent_total >= MAIL_DAILY_LIMIT:
        logger.error(f"mail daily limit reached: {sent_total}/{MAIL_DAILY_LIMIT}")
        raise mail_client.MailUnavailableError(mail_client.UNAVAILABLE_MESSAGE)


def _match_email_code(
    db: Session, email: str, purpose: str, code: str
) -> tuple[EmailVerificationCode | None, str | None]:
    """`(코드 행, 오류 문구)`. 가장 최근에 보낸 코드만 유효하다 — 다시 받으면 이전 코드는 죽는다.

    틀리면 횟수를 올리고 flush 만 한다. 커밋은 호출부가 한다(오류로 끝나도 커밋해야 횟수가 남는다).
    """
    row = db.scalar(
        select(EmailVerificationCode)
        .where(EmailVerificationCode.email == email, EmailVerificationCode.purpose == purpose)
        .order_by(EmailVerificationCode.created_at.desc(), EmailVerificationCode.id.desc())
        .limit(1)
    )

    if (
        row is None
        or row.consumed_at is not None
        or row.expires_at <= datetime.now(UTC)
        or row.attempt_count >= EMAIL_CODE_MAX_ATTEMPTS
    ):
        return None, CODE_EXPIRED_MESSAGE

    if not secrets.compare_digest(row.code_hash, _hash_email_code(email, purpose, code.strip())):
        row.attempt_count += 1
        db.flush()
        return None, CODE_WRONG_MESSAGE

    return row, None


def _require_nickname(nickname: str) -> str:
    nickname = nickname.strip()

    if not nickname:
        raise BadRequestError("닉네임을 입력해주세요.")

    return nickname


def _is_nickname_taken(db: Session, nickname: str) -> bool:
    # 카카오·Apple 회원 닉네임까지 비교한다(그룹에서 같은 화면에 나란히 보인다). 대소문자·앞뒤 공백 무시.
    # ponytail: 앱 레벨 검사라 동시 가입 두 건은 같은 닉네임이 될 수 있다. 카카오 닉네임끼리는 원래 겹치므로
    # DB UNIQUE 를 걸 수 없다 — 문제가 되면 이메일 회원만의 부분 유니크 인덱스를 둔다.
    return db.scalar(
        select(func.count())
        .select_from(User)
        .where(func.lower(func.trim(User.nickname)) == nickname.lower())
    ) > 0


def _ensure_password_rule(password: str) -> None:
    if not (
        PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH
        and _PASSWORD_LETTER.search(password)
        and _PASSWORD_DIGIT.search(password)
    ):
        raise BadRequestError(PASSWORD_RULE_MESSAGE)


def _hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def _verify_password(password: str, stored: str | None) -> bool:
    _, n, r, p, salt, digest = (stored or _dummy_password_hash()).split("$")
    expected = base64.b64decode(digest)
    candidate = hashlib.scrypt(
        password.encode("utf-8"),
        salt=base64.b64decode(salt),
        n=int(n),
        r=int(r),
        p=int(p),
        dklen=len(expected),
    )
    return stored is not None and hmac.compare_digest(candidate, expected)


@cache
def _dummy_password_hash() -> str:
    # 없는 회원의 로그인도 같은 비용을 치르게 하는 값. import 시점이 아니라 처음 쓸 때 만든다.
    return _hash_password(secrets.token_urlsafe(16))


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _hash_email_code(email: str, purpose: str, code: str) -> str:
    # 6자리는 해시만으로는 대입이 쉬워 pepper 를 넣는다. 주소·용도를 묶어 다른 행의 코드로 쓰지 못하게 한다.
    return _sign(f"{purpose}:{email}:{code}")


def _signup_code_body(code: str) -> str:
    return (
        f"케어테이블 가입 인증 코드는 {code} 입니다.\n\n"
        f"앱의 인증 코드 칸에 입력해주세요. {EMAIL_CODE_TTL_MINUTES}분 동안 쓸 수 있어요.\n"
        "가입을 요청한 적이 없다면 이 메일은 무시하셔도 됩니다."
    )


def _already_registered_body() -> str:
    return (
        "이 이메일로 가입된 케어테이블 계정이 이미 있어요.\n\n"
        "앱에서 '이메일로 로그인'을 눌러 주세요. 비밀번호가 기억나지 않으면 "
        "'비밀번호를 잊었어요'에서 다시 정할 수 있어요.\n"
        "가입을 요청한 적이 없다면 이 메일은 무시하셔도 됩니다."
    )


def _reset_code_body(code: str) -> str:
    return (
        f"케어테이블 비밀번호 재설정 코드는 {code} 입니다.\n\n"
        f"앱의 인증 코드 칸에 입력하고 새 비밀번호를 정해주세요. {EMAIL_CODE_TTL_MINUTES}분 동안 쓸 수 있어요.\n"
        "비밀번호를 바꾸면 모든 기기에서 로그아웃됩니다.\n"
        "요청한 적이 없다면 이 메일은 무시하셔도 됩니다. 비밀번호는 바뀌지 않아요."
    )


def _ensure_signup_agreements(
    agreed_terms: bool,
    agreed_privacy: bool,
    terms_version: str | None,
    privacy_version: str | None,
) -> None:
    """가입 요청을 외부 자원(연동 코드·Apple 토큰)을 쓰기 **전에** 거른다.

    미동의·옛 문서 요청이 1회용 코드만 태우고 400 이 되면, 사용자는 로그인부터 다시 해야 한다.
    """
    if not (agreed_terms and agreed_privacy):
        raise BadRequestError("서비스 이용약관과 개인정보 처리방침에 모두 동의해야 가입할 수 있습니다.")

    if terms_version is not None:
        ensure_current_version(TERMS, terms_version)

    if privacy_version is not None:
        ensure_current_version(PRIVACY, privacy_version)


def _create_member(
    db: Session,
    user: User,
    plan_code: str | None,
    terms_version: str | None,
    privacy_version: str | None,
) -> tuple[User, AuthSession, str]:
    db.add(user)
    db.flush()

    # 회원·동의·구독은 한 트랜잭션이다. 셋 중 하나만 남는 상태(동의 없는 회원, 요금제 없는
    # 회원)가 생기면 안 된다. 없는 plan_code 는 여기서 BadRequestError → 400.
    record_signup_consents(db, user.id, terms_version, privacy_version)
    create_subscription(db, user.id, plan_code)
    return _start_session(db, user)


# ---- 세션 ----

def get_user_by_session_token(db: Session, token: str) -> User | None:
    now = datetime.now(UTC)
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.token == _hash_token(token),
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
            AuthSession.token == _hash_token(token),
            AuthSession.revoked_at.is_(None),
        )
    )

    # 이미 폐기됐거나 없는 토큰이면 조용히 통과한다 (로그아웃은 멱등).
    if not session:
        return

    session.revoked_at = datetime.now(UTC)
    db.commit()


def _get_user_by_kakao_id(db: Session, kakao_id: str) -> User | None:
    return db.scalar(select(User).where(User.kakao_id == kakao_id))


def _get_user_by_apple_sub(db: Session, apple_sub: str) -> User | None:
    return db.scalar(select(User).where(User.apple_sub == apple_sub))


def _get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


def _start_session(db: Session, user: User) -> tuple[User, AuthSession, str]:
    session, raw_token = _create_session(user.id)
    db.add(session)
    db.commit()
    db.refresh(user)
    db.refresh(session)
    return user, session, raw_token


def _create_session(user_id: int) -> tuple[AuthSession, str]:
    # DB에는 해시만 저장하고 원문은 발급 응답에서만 반환한다 (DB 유출 시 재사용 방지).
    raw_token = secrets.token_urlsafe(48)
    session = AuthSession(
        user_id=user_id,
        token=_hash_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(days=SESSION_TTL_DAYS),
    )
    return session, raw_token


def _hash_token(token: str) -> str:
    # 토큰·연동 코드 모두 256비트 이상 난수라 pepper 없이 단순 sha256으로 충분하다.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _sign(raw: str) -> str:
    return hmac.new(
        AUTH_CODE_PEPPER.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256
    ).hexdigest()


# 정기 정리 배치 보존창.
# 연동 코드·이메일 인증 코드: 발급 1일 뒤 삭제 (TTL 10분을 한참 지난 뒤. 이메일 코드의 하루 한도가
# 지난 24시간을 세므로 그보다 일찍 지우면 안 된다).
# 세션: 만료·폐기 7일 뒤 삭제 (짧은 감사 유예).
CODE_RETENTION_DAYS = 1
SESSION_RETENTION_DAYS = 7


def purge_expired_auth(db: Session) -> dict[str, int]:
    """만료된 연동 코드·이메일 인증 코드와 만료·폐기된 세션을 물리 삭제한다. 정기 배치용(멱등).

    반환: 삭제 건수 `{"codes": n, "sessions": m}` (codes 는 두 코드 테이블의 합).
    """
    now = datetime.now(UTC)
    code_cutoff = now - timedelta(days=CODE_RETENTION_DAYS)

    codes_deleted = db.execute(
        delete(KakaoLinkCode).where(KakaoLinkCode.created_at < code_cutoff)
    ).rowcount
    codes_deleted += db.execute(
        delete(EmailVerificationCode).where(EmailVerificationCode.created_at < code_cutoff)
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
