"""동의 버전 대조 회귀 (2026-07-16).

동의 이력의 존재 이유는 **"누가 무엇에 동의했는지"의 증빙**이다. 그런데 2026-07-16 이전에는
가입 요청에 버전 필드가 아예 없어서, 앱이 화면에 무엇을 그렸든 서버가 자기 상수(TERMS_VERSION)를
박았다. 문서를 개정하고 구버전 앱이 남아 있으면 **사용자는 v1.0 을 보고 동의했는데 DB 에는
"2.0 에 동의함"으로 기록**된다 — 증빙이 거짓이 되는 것이다.

민감정보 동의는 반대로 앱이 버전을 보내는데 서버가 검증하지 않아, 아무 문자열이나 그대로
저장됐다(실측: "존재하지-않는-버전-9.9" → 201).

카카오 회원번호는 다른 테스트와 겹치지 않도록 8500000xxx 대역을 쓴다.
"""

import pytest
from sqlalchemy import select

from models.auth_model import User
from models.consent_model import UserConsent
from services import auth_service, consent_service


def _issue_link_code(db, kakao_id: str) -> str:
    raw_code, _ = auth_service.create_link_code(db, kakao_id, "버전테스터")
    return raw_code


def _consents_of(db, user_id: int) -> dict[str, str]:
    rows = db.scalars(select(UserConsent).where(UserConsent.user_id == user_id)).all()
    return {row.kind: row.version for row in rows}


# ---- 가입: 앱이 보낸 버전을 기록한다 ----

def test_signup_records_the_version_the_app_actually_showed(db):
    """앱이 그린 문서의 버전이 그대로 남아야 증빙이 성립한다."""
    code = _issue_link_code(db, "8500000001")

    user, _, _ = auth_service.kakao_signup(
        db,
        code,
        True,
        True,
        None,
        consent_service.TERMS_VERSION,
        consent_service.PRIVACY_VERSION,
    )

    stored = _consents_of(db, user.id)
    assert stored["terms"] == consent_service.TERMS_VERSION
    assert stored["privacy"] == consent_service.PRIVACY_VERSION


def test_signup_with_stale_terms_version_is_rejected(db):
    """옛 약관을 띄운 앱의 가입을 막는다 — 그 동의는 현재 약관에 대한 것이 아니다."""
    code = _issue_link_code(db, "8500000002")

    with pytest.raises(ValueError):
        auth_service.kakao_signup(db, code, True, True, None, "0.9", consent_service.PRIVACY_VERSION)


def test_signup_with_stale_privacy_version_is_rejected(db):
    code = _issue_link_code(db, "8500000003")

    with pytest.raises(ValueError):
        auth_service.kakao_signup(db, code, True, True, None, consent_service.TERMS_VERSION, "0.9")


def test_stale_version_does_not_consume_the_link_code(db):
    """버전 대조는 코드 소비 **전**이다.

    1회용 연동 코드가 타 버리면 사용자는 카카오 로그인부터 다시 해야 한다. 앱을 업데이트한 뒤
    같은 코드로 이어서 가입할 수 있어야 한다 (미동의 거절과 같은 규칙).
    """
    code = _issue_link_code(db, "8500000004")

    with pytest.raises(ValueError):
        auth_service.kakao_signup(db, code, True, True, None, "0.9", "0.9")

    user, _, _ = auth_service.kakao_signup(
        db,
        code,
        True,
        True,
        None,
        consent_service.TERMS_VERSION,
        consent_service.PRIVACY_VERSION,
    )
    assert user.kakao_id == "8500000004"


def test_signup_without_versions_falls_back_to_server_constants(db):
    """버전을 보내지 않는 구버전 앱은 그대로 가입된다 (하위호환).

    증빙으로서는 약하다 — 앱이 무엇을 보여줬는지 알 수 없다. 두 필드가 앱에 자리잡으면 필수로
    좁히는 것이 맞다.
    """
    user, _, _ = auth_service.kakao_signup(db, _issue_link_code(db, "8500000005"), True, True)

    stored = _consents_of(db, user.id)
    assert stored["terms"] == consent_service.TERMS_VERSION
    assert stored["privacy"] == consent_service.PRIVACY_VERSION


# ---- 민감정보 동의: 아무 문자열이나 받지 않는다 ----

def _make_user(db, kakao_id: str) -> User:
    user = User(kakao_id=kakao_id, nickname="버전테스터")
    db.add(user)
    db.commit()
    return user


def test_create_consent_rejects_unknown_version(db):
    """실측으로 확인된 구멍: 임의 문자열이 201 로 저장됐다."""
    user = _make_user(db, "8500000006")

    with pytest.raises(ValueError):
        consent_service.create_consent(db, user.id, "sensitive_health", "존재하지-않는-버전-9.9")

    assert _consents_of(db, user.id) == {}


def test_create_consent_accepts_current_version(db):
    user = _make_user(db, "8500000007")

    consent_service.create_consent(
        db, user.id, "sensitive_health", consent_service.SENSITIVE_HEALTH_VERSION
    )

    assert _consents_of(db, user.id)["sensitive_health"] == consent_service.SENSITIVE_HEALTH_VERSION


def test_unknown_kind_passes_through(db):
    """모르는 kind 는 통과시킨다 — 동의 종류가 늘 때 서버만 먼저 배포돼도 깨지지 않아야 한다."""
    consent_service.ensure_current_version("some_future_kind", "whatever")


def test_version_formats_differ_by_kind_and_that_is_intentional(db):
    """terms·privacy 는 '1.0', sensitive_health 는 'v1.0' 이다.

    기존 데이터가 그렇게 쌓여 있어 통일하려면 마이그레이션이 필요하다. 검증은 kind 별 비교라
    지장이 없다 — 이 테스트는 그 사실을 문서화하고, 무심코 한쪽만 바꾸면 실패한다.
    """
    assert consent_service.TERMS_VERSION == "1.0"
    assert consent_service.PRIVACY_VERSION == "1.0"
    assert consent_service.SENSITIVE_HEALTH_VERSION == "v1.0"
