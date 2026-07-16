"""인증 — 카카오 로그인 단일 수단.

SMS(휴대폰 OTP)는 2026-07-14에 제거했다. 인증 수단이 카카오 하나뿐이므로, 카카오 설정이
없으면 아무도 로그인하지 못한다 (`ensure_production_kakao_config`).

흐름 (DATA_MODEL.md 21장):
  앱 → GET /api/auth/kakao/start        (서버가 state 서명 후 카카오로 302)
  카카오 → GET /api/auth/kakao/callback (서버가 코드 교환·프로필 조회 → **1회용 연동 코드** 발급)
  서버 → 앱 딥링크 (kcalairn://auth?code=...&is_new=true|false)
  앱 → POST /api/auth/kakao/login  또는  /api/auth/kakao/signup (연동 코드 → 세션 토큰)
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta

from timeutil import UTC

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from models.auth_model import AuthSession, KakaoLinkCode, User
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


class StateError(Exception):
    """OAuth state 위조·만료. api 레이어가 400으로 변환한다 (CSRF 방어)."""


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
        raise ValueError("로그인 정보가 만료되었습니다. 다시 시도해주세요.")

    link_code.consumed_at = now
    db.flush()
    return link_code


# ---- 로그인 · 가입 ----

def kakao_login(db: Session, raw_code: str) -> tuple[User, AuthSession, str]:
    link_code = _consume_link_code(db, raw_code)
    user = _get_user_by_kakao_id(db, link_code.kakao_id)

    if user is None:
        raise LookupError("가입되지 않은 카카오 계정입니다. 회원가입을 먼저 진행해주세요.")

    # 카카오에서 닉네임을 바꿨으면 따라간다 (그룹에 보이는 이름이다).
    if link_code.nickname and link_code.nickname != user.nickname:
        user.nickname = link_code.nickname

    session, raw_token = _create_session(user.id)
    db.add(session)
    db.commit()
    db.refresh(user)
    db.refresh(session)
    return user, session, raw_token


def kakao_signup(
    db: Session,
    raw_code: str,
    agreed_terms: bool,
    agreed_privacy: bool,
    plan_code: str | None = None,
    terms_version: str | None = None,
    privacy_version: str | None = None,
) -> tuple[User, AuthSession, str]:
    # 동의는 회원 행을 만들기 전에 본다 — 미동의 요청이 연동 코드만 소비하고 끝나지 않게 한다.
    if not (agreed_terms and agreed_privacy):
        raise ValueError("서비스 이용약관과 개인정보 처리방침에 모두 동의해야 가입할 수 있습니다.")

    # 버전 대조도 **코드 소비 전**이다. 옛 문서를 띄운 앱의 요청이 1회용 코드만 태우고 400 이
    # 되면, 사용자는 카카오 로그인부터 다시 해야 한다.
    if terms_version is not None:
        ensure_current_version(TERMS, terms_version)

    if privacy_version is not None:
        ensure_current_version(PRIVACY, privacy_version)

    link_code = _consume_link_code(db, raw_code)

    if _get_user_by_kakao_id(db, link_code.kakao_id) is not None:
        raise ValueError("이미 가입된 카카오 계정입니다. 로그인으로 진행해주세요.")

    user = User(kakao_id=link_code.kakao_id, nickname=link_code.nickname)
    db.add(user)
    db.flush()

    # 회원·동의·구독은 한 트랜잭션이다. 셋 중 하나만 남는 상태(동의 없는 회원, 요금제 없는
    # 회원)가 생기면 안 된다. 없는 plan_code 는 여기서 ValueError → 400.
    record_signup_consents(db, user.id, terms_version, privacy_version)
    create_subscription(db, user.id, plan_code)

    session, raw_token = _create_session(user.id)
    db.add(session)
    db.commit()
    db.refresh(user)
    db.refresh(session)
    return user, session, raw_token


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
# 연동 코드: 발급 1일 뒤 삭제 (TTL 10분을 한참 지난 뒤).
# 세션: 만료·폐기 7일 뒤 삭제 (짧은 감사 유예).
CODE_RETENTION_DAYS = 1
SESSION_RETENTION_DAYS = 7


def purge_expired_auth(db: Session) -> dict[str, int]:
    """만료된 연동 코드와 만료·폐기된 세션을 물리 삭제한다. 정기 배치용(멱등).

    반환: 삭제 건수 `{"codes": n, "sessions": m}`.
    """
    now = datetime.now(UTC)

    codes_deleted = db.execute(
        delete(KakaoLinkCode).where(
            KakaoLinkCode.created_at < now - timedelta(days=CODE_RETENTION_DAYS)
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
