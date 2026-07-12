"""services/auth_service.py 회귀 테스트.

v18 인증 견고화(OTP 브루트포스 방어·발급 레이트리밋·세션 토큰 해싱·단일 유효 코드·
휴대폰 검증·운영 설정 게이트)의 계약을 코드로 고정한다.

전화번호는 개발 DB의 잔존 데이터와 겹치지 않도록 0109999xxxx 대역을 쓴다
(레이트리밋 카운트가 기존 행에 오염되는 것을 피하기 위함).
"""

from datetime import datetime, timedelta

from timeutil import UTC

import pytest
from sqlalchemy import select, update

import services.auth_service as auth_service
from models.auth_model import AuthSession, PhoneVerificationCode, User


def _issue_signup_code(db, phone: str) -> str:
    _, code = auth_service.create_signup_code(db, phone)
    assert code is not None, "AUTH_INCLUDE_DEV_CODE가 True여야 평문 코드가 반환된다"
    return code


def _wrong_code(code: str) -> str:
    # 실제 코드와 절대 겹치지 않는 6자리 코드.
    return f"{(int(code) + 1) % 1_000_000:06d}"


def _backdate_codes(db, phone: str, seconds: int) -> None:
    # 해당 번호의 모든 코드 created_at을 과거로 옮겨 쿨다운을 우회한다.
    db.execute(
        update(PhoneVerificationCode)
        .where(PhoneVerificationCode.phone_number == phone)
        .values(created_at=datetime.now(UTC) - timedelta(seconds=seconds))
    )
    db.flush()


# --- 휴대폰 번호 정규화·검증 (순수 함수) -------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("010-1234-5678", "01012345678"),
        ("01012345678", "01012345678"),
        ("+82 10-1234-5678", "01012345678"),
        ("0111234567", "0111234567"),  # 011 + 7자리
    ],
)
def test_normalize_accepts_mobile(raw, expected):
    assert auth_service.normalize_phone_number(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "021234567",    # 유선(02)
        "0212345678",   # 유선(02)
        "010123",       # 너무 짧음
        "abcdefg",      # 숫자 없음
        "0201234567",   # 유선(02)
    ],
)
def test_normalize_rejects_non_mobile(raw):
    with pytest.raises(ValueError):
        auth_service.normalize_phone_number(raw)


# --- 가입·로그인 해피 패스 ---------------------------------------------------

def test_signup_verify_creates_user_and_session(db):
    phone = "01099991000"
    code = _issue_signup_code(db, phone)
    user, session, raw_token = auth_service.verify_signup_code(db, phone, code)

    assert user.phone_number == phone
    assert user.is_phone_verified is True
    assert session.user_id == user.id
    assert raw_token  # 원문 토큰이 반환된다


def test_signup_then_login(db):
    phone = "01099991001"
    code = _issue_signup_code(db, phone)
    auth_service.verify_signup_code(db, phone, code)

    _backdate_codes(db, phone, seconds=61)  # 가입 코드 발급 직후라 쿨다운 회피
    _, login_code = auth_service.create_login_code(db, phone)
    user, _, raw_token = auth_service.verify_login_code(db, phone, login_code)

    assert user.phone_number == phone
    assert raw_token


def test_duplicate_signup_rejected(db):
    phone = "01099991002"
    code = _issue_signup_code(db, phone)
    auth_service.verify_signup_code(db, phone, code)

    with pytest.raises(ValueError):
        auth_service.create_signup_code(db, phone)


def test_login_unknown_phone_rejected(db):
    with pytest.raises(ValueError):
        auth_service.create_login_code(db, "01099991003")


# --- OTP 브루트포스 방어 -----------------------------------------------------

def test_five_wrong_attempts_keep_code_valid(db):
    phone = "01099992000"
    code = _issue_signup_code(db, phone)
    wrong = _wrong_code(code)

    for _ in range(5):  # 5회까지는 코드가 살아 있어야 한다 (한도 = 5)
        with pytest.raises(ValueError):
            auth_service.verify_signup_code(db, phone, wrong)

    user, _, _ = auth_service.verify_signup_code(db, phone, code)
    assert user.phone_number == phone


def test_sixth_wrong_attempt_invalidates_code(db):
    phone = "01099992001"
    code = _issue_signup_code(db, phone)
    wrong = _wrong_code(code)

    for _ in range(6):  # 6번째 실패에서 attempt_count > 5 → 코드 무효화
        with pytest.raises(ValueError):
            auth_service.verify_signup_code(db, phone, wrong)

    # 정답을 넣어도 이미 무효화되어 실패한다.
    with pytest.raises(ValueError):
        auth_service.verify_signup_code(db, phone, code)


# --- 발급 레이트리밋 ---------------------------------------------------------

def test_cooldown_blocks_immediate_reissue(db):
    phone = "01099993000"
    auth_service.create_signup_code(db, phone)
    with pytest.raises(auth_service.RateLimitError):
        auth_service.create_signup_code(db, phone)


def test_reissue_allowed_after_cooldown(db):
    phone = "01099993001"
    auth_service.create_signup_code(db, phone)
    _backdate_codes(db, phone, seconds=61)  # 쿨다운(60초) 경과
    _, code = auth_service.create_signup_code(db, phone)
    assert code is not None


def test_hourly_limit_blocks_after_five(db):
    phone = "01099993002"
    now = datetime.now(UTC)
    # 1시간 내이지만 최신도 60초보다 오래된 코드 5개를 심는다 (쿨다운은 통과, 시간당 한도는 초과).
    for i in range(5):
        db.add(
            PhoneVerificationCode(
                phone_number=phone,
                purpose="signup",
                code_hash="x" * 64,
                expires_at=now + timedelta(minutes=5),
                created_at=now - timedelta(minutes=2 + i * 10),  # 2·12·22·32·42분 전
            )
        )
    db.flush()

    with pytest.raises(auth_service.RateLimitError) as exc:
        auth_service.create_signup_code(db, phone)
    assert "1시간" in str(exc.value)  # 쿨다운이 아니라 시간당 한도 메시지


def test_new_code_invalidates_previous(db):
    phone = "01099994000"
    _, old_code = auth_service.create_signup_code(db, phone)
    _backdate_codes(db, phone, seconds=61)
    _, new_code = auth_service.create_signup_code(db, phone)

    # 이전 코드는 무효 → 검증 실패
    with pytest.raises(ValueError):
        auth_service.verify_signup_code(db, phone, old_code)
    # 새 코드는 유효
    user, _, _ = auth_service.verify_signup_code(db, phone, new_code)
    assert user.phone_number == phone


# --- 세션 토큰 해싱 ----------------------------------------------------------

def test_session_token_stored_hashed_and_resolvable(db):
    phone = "01099995000"
    code = _issue_signup_code(db, phone)
    user, session, raw_token = auth_service.verify_signup_code(db, phone, code)

    assert session.token != raw_token          # DB에는 원문이 아니라 해시
    assert len(session.token) == 64             # sha256 hex
    resolved = auth_service.get_user_by_session_token(db, raw_token)
    assert resolved is not None and resolved.id == user.id
    # 저장된 해시값 자체로는 조회되지 않는다 (원문만 유효).
    assert auth_service.get_user_by_session_token(db, session.token) is None


def test_revoke_session_is_idempotent(db):
    phone = "01099995001"
    code = _issue_signup_code(db, phone)
    _, _, raw_token = auth_service.verify_signup_code(db, phone, code)

    auth_service.revoke_session_token(db, raw_token)
    assert auth_service.get_user_by_session_token(db, raw_token) is None
    # 두 번째 폐기 호출도 예외 없이 통과한다 (로그아웃 멱등).
    auth_service.revoke_session_token(db, raw_token)


# --- 운영 설정 게이트 --------------------------------------------------------

def test_production_config_rejects_insecure_pepper(monkeypatch):
    monkeypatch.setattr(auth_service, "AUTH_CODE_PEPPER", "development-only-pepper")
    monkeypatch.setattr(auth_service, "AUTH_INCLUDE_DEV_CODE", False)
    with pytest.raises(RuntimeError):
        auth_service.ensure_production_auth_config()


def test_production_config_rejects_dev_code_enabled(monkeypatch):
    monkeypatch.setattr(auth_service, "AUTH_CODE_PEPPER", "a-real-unique-secret")
    monkeypatch.setattr(auth_service, "AUTH_INCLUDE_DEV_CODE", True)
    with pytest.raises(RuntimeError):
        auth_service.ensure_production_auth_config()


def test_production_config_passes_when_secure(monkeypatch):
    monkeypatch.setattr(auth_service, "AUTH_CODE_PEPPER", "a-real-unique-secret")
    monkeypatch.setattr(auth_service, "AUTH_INCLUDE_DEV_CODE", False)
    auth_service.ensure_production_auth_config()  # 예외가 없어야 한다


# --- 정리 배치 ------------------------------------------------------------

def test_purge_deletes_old_codes_keeps_recent(db):
    phone = "01099996000"
    now = datetime.now(UTC)
    # 오래된 코드(2일 전) + 최근 코드(방금)
    db.add(PhoneVerificationCode(
        phone_number=phone, purpose="signup", code_hash="x" * 64,
        expires_at=now, created_at=now - timedelta(days=2),
    ))
    db.add(PhoneVerificationCode(
        phone_number=phone, purpose="signup", code_hash="y" * 64,
        expires_at=now + timedelta(minutes=5), created_at=now,
    ))
    db.flush()

    result = auth_service.purge_expired_auth(db)
    assert result["codes"] >= 1

    remaining = db.scalars(
        select(PhoneVerificationCode.created_at).where(
            PhoneVerificationCode.phone_number == phone
        )
    ).all()
    # 최근 코드만 남는다.
    assert all(created > now - timedelta(days=1) for created in remaining)


def test_purge_deletes_old_sessions_keeps_active(db):
    now = datetime.now(UTC)
    user = User(phone_number="01099996001", is_phone_verified=True)
    db.add(user)
    db.flush()

    # 8일 전 만료된 세션 + 활성 세션
    db.add(AuthSession(user_id=user.id, token="old" + "a" * 61,
                       expires_at=now - timedelta(days=8)))
    active_token = "new" + "b" * 61
    db.add(AuthSession(user_id=user.id, token=active_token,
                       expires_at=now + timedelta(days=30)))
    db.flush()

    auth_service.purge_expired_auth(db)

    tokens = db.scalars(
        select(AuthSession.token).where(AuthSession.user_id == user.id)
    ).all()
    assert active_token in tokens  # 활성 세션 보존
    assert "old" + "a" * 61 not in tokens  # 오래 만료된 세션 삭제
