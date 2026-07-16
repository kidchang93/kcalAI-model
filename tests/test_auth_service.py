"""카카오 로그인 인증 회귀 (DATA_MODEL.md 21장).

카카오 서버는 부르지 않는다 — 외부 호출은 콜백 라우트(`kakao_client`)에만 있고, 여기서는 그
뒤의 **연동 코드 → 세션** 구간을 검증한다. 카카오 회원번호는 9000000xxx 대역을 쓴다.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from models.auth_model import AuthSession, KakaoLinkCode, User
from services import auth_service, consent_service, subscription_service
from timeutil import UTC


def _issue_link_code(db, kakao_id: str, nickname: str = "테스터") -> str:
    raw_code, _ = auth_service.create_link_code(db, kakao_id, nickname)
    return raw_code


# ---- OAuth state (CSRF) ----

def test_state_roundtrip_preserves_platform():
    assert auth_service.verify_state(auth_service.create_state("web")) == "web"


def test_tampered_state_is_rejected():
    state = auth_service.create_state("native")
    payload, _, signature = state.partition(".")

    # 본문 위조 (플랫폼·만료를 바꾸려는 시도).
    with pytest.raises(auth_service.StateError):
        auth_service.verify_state(f"{payload}x.{signature}")

    # 서명 위조.
    with pytest.raises(auth_service.StateError):
        auth_service.verify_state(f"{payload}.{signature[:-1]}0")

    # 서명 누락 — 우리가 시작시키지 않은 콜백이다.
    with pytest.raises(auth_service.StateError):
        auth_service.verify_state(payload)


# ---- 가입 ----

def test_signup_creates_user_with_kakao_id_and_nickname(db):
    code = _issue_link_code(db, "9000000001", "홍길동")

    user, session, raw_token = auth_service.kakao_signup(db, code, True, True)

    assert user.kakao_id == "9000000001"
    assert user.nickname == "홍길동"
    # 세션 토큰은 원문이 아니라 해시로 저장된다.
    assert session.token != raw_token
    assert auth_service.get_user_by_session_token(db, raw_token).id == user.id

    # 가입 필수 동의와 무료 요금제가 같은 트랜잭션에서 만들어졌다.
    kinds = {consent.kind for consent in consent_service.list_consents(db, user.id)}
    assert kinds == {"terms", "privacy"}
    assert subscription_service.get_subscription(db, user.id).plan_code == "lite"


def test_signup_paid_plan_still_starts_free(db):
    # 가입 요청의 plan_code 를 그대로 믿으면 **결제 없이 Premium 을 얻는 경로**가 된다.
    # 유료를 골랐어도 무료로 시작하고, 업그레이드는 결제(/api/billing/confirm)를 거쳐야 한다.
    user, _, _ = auth_service.kakao_signup(
        db, _issue_link_code(db, "9000000002"), True, True, "premium"
    )

    assert subscription_service.get_subscription(db, user.id).plan_code == "lite"
    assert subscription_service.get_user_plan(db, user.id).code == "lite"


def test_signup_without_consent_is_rejected_and_keeps_code_usable(db):
    code = _issue_link_code(db, "9000000003")

    with pytest.raises(ValueError):
        auth_service.kakao_signup(db, code, True, False)

    # 동의를 회원 생성 **전에** 보므로 연동 코드가 소비되지 않는다 — 동의 후 그대로 재시도된다.
    user, _, _ = auth_service.kakao_signup(db, code, True, True)
    assert user.kakao_id == "9000000003"


def test_duplicate_signup_is_rejected(db):
    auth_service.kakao_signup(db, _issue_link_code(db, "9000000004"), True, True)

    with pytest.raises(ValueError):
        auth_service.kakao_signup(db, _issue_link_code(db, "9000000004"), True, True)


def test_signup_creates_user_without_phone_number(db):
    # SMS 제거 후 회원은 전화번호 없이 만들어진다 (컬럼은 비즈앱 전환 대비로 남아 있다).
    user, _, _ = auth_service.kakao_signup(db, _issue_link_code(db, "9000000005"), True, True)

    assert db.scalar(select(User.phone_number).where(User.id == user.id)) is None


# ---- 로그인 ----

def test_login_requires_existing_user(db):
    with pytest.raises(LookupError):
        auth_service.kakao_login(db, _issue_link_code(db, "9000000010"))


def test_signup_then_login(db):
    signed_up, _, _ = auth_service.kakao_signup(db, _issue_link_code(db, "9000000011"), True, True)

    user, _, raw_token = auth_service.kakao_login(db, _issue_link_code(db, "9000000011"))

    assert user.id == signed_up.id
    assert auth_service.get_user_by_session_token(db, raw_token).id == signed_up.id


def test_login_refreshes_nickname_from_kakao(db):
    auth_service.kakao_signup(db, _issue_link_code(db, "9000000012", "옛이름"), True, True)

    # 카카오에서 닉네임을 바꾸면 따라간다 — 그룹 멤버에게 보이는 이름이다.
    user, _, _ = auth_service.kakao_login(db, _issue_link_code(db, "9000000012", "새이름"))

    assert user.nickname == "새이름"


# ---- 연동 코드 ----

def test_link_code_is_single_use(db):
    code = _issue_link_code(db, "9000000020")
    auth_service.kakao_signup(db, code, True, True)

    # 딥링크 URL 이 유출돼도 재사용되면 안 된다.
    with pytest.raises(ValueError):
        auth_service.kakao_login(db, code)


def test_new_link_code_invalidates_the_previous_one(db):
    first = _issue_link_code(db, "9000000021")
    second = _issue_link_code(db, "9000000021")

    with pytest.raises(ValueError):
        auth_service.kakao_signup(db, first, True, True)

    user, _, _ = auth_service.kakao_signup(db, second, True, True)
    assert user.kakao_id == "9000000021"


def test_expired_link_code_is_rejected(db):
    code = _issue_link_code(db, "9000000022")

    stored = db.scalar(select(KakaoLinkCode).where(KakaoLinkCode.kakao_id == "9000000022"))
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    with pytest.raises(ValueError):
        auth_service.kakao_signup(db, code, True, True)


def test_link_code_is_stored_hashed(db):
    raw_code = _issue_link_code(db, "9000000023")

    stored = db.scalar(select(KakaoLinkCode).where(KakaoLinkCode.kakao_id == "9000000023"))
    assert stored.code_hash != raw_code
    assert len(stored.code_hash) == 64


def test_is_new_user_flag_tells_the_app_which_screen_to_show(db):
    _, is_new = auth_service.create_link_code(db, "9000000030", "신규")
    assert is_new is True

    auth_service.kakao_signup(db, _issue_link_code(db, "9000000030"), True, True)

    _, is_new_again = auth_service.create_link_code(db, "9000000030", "신규")
    assert is_new_again is False


# ---- 세션 ----

def test_revoke_session_is_idempotent(db):
    _, _, raw_token = auth_service.kakao_signup(db, _issue_link_code(db, "9000000040"), True, True)

    auth_service.revoke_session_token(db, raw_token)
    assert auth_service.get_user_by_session_token(db, raw_token) is None

    # 두 번째 폐기도 조용히 통과한다 (로그아웃은 멱등).
    auth_service.revoke_session_token(db, raw_token)


def test_expired_session_is_rejected(db):
    _, session, raw_token = auth_service.kakao_signup(
        db, _issue_link_code(db, "9000000041"), True, True
    )

    stored = db.scalar(select(AuthSession).where(AuthSession.id == session.id))
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    assert auth_service.get_user_by_session_token(db, raw_token) is None


def test_purge_removes_expired_codes(db):
    code = _issue_link_code(db, "9000000050")

    stored = db.scalar(select(KakaoLinkCode).where(KakaoLinkCode.kakao_id == "9000000050"))
    stored.created_at = datetime.now(UTC) - timedelta(days=auth_service.CODE_RETENTION_DAYS + 1)
    db.commit()

    result = auth_service.purge_expired_auth(db)

    assert result["codes"] >= 1
    assert db.scalar(select(KakaoLinkCode).where(KakaoLinkCode.kakao_id == "9000000050")) is None

    with pytest.raises(ValueError):
        auth_service.kakao_login(db, code)
