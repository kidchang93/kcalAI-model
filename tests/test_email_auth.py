"""이메일 가입·로그인·비밀번호 재설정 회귀 — DATA_MODEL.md 21장 '이메일 가입'.

**메일은 보내지 않는다.** `mail_client.send_mail` 을 대체해 받는 주소·제목·본문을 기록한다.
지키는 것: 코드 대입이 막힌다 · 응답으로 이메일의 가입 여부가 새지 않는다 · 비밀번호 원문이
남지 않는다 · 재설정이 기존 세션을 끊는다 · 탈퇴가 코드까지 지운다.
"""

import re
import smtplib
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from api.auth_api import router
from database import get_db
from factories import make_user
from main import add_service_error_handlers
from models.auth_model import AuthSession, EmailVerificationCode, User
from models.consent_model import UserConsent
from models.subscription_model import UserSubscription
from services import account_service, auth_service, mail_client
from timeutil import UTC

EMAIL = "Patient.Kim@Example.com"
NORMALIZED = "patient.kim@example.com"
PASSWORD = "kidney2026"
# 공유 개발 DB 의 기존 회원과 겹치지 않을 이름 — 겹치면 중복확인에 걸려 가입 테스트가 깨진다.
NICKNAME = "이메일가입테스터"


@pytest.fixture
def outbox(monkeypatch) -> list[dict]:
    sent: list[dict] = []
    monkeypatch.setattr(
        mail_client, "send_mail", lambda to, subject, body: sent.append({"to": to, "subject": subject, "body": body})
    )
    return sent


@pytest.fixture
def client(db, outbox):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    add_service_error_handlers(app)
    app.dependency_overrides[get_db] = lambda: db

    with TestClient(app) as test_client:
        yield test_client


def _code_in(mail: dict) -> str:
    return re.search(r"\b(\d{6})\b", mail["subject"]).group(1)


def _age_codes(db, email: str = NORMALIZED, seconds: int = 120) -> None:
    """재요청 간격을 건너뛰려고 이미 보낸 코드를 과거로 민다."""
    db.execute(
        update(EmailVerificationCode)
        .where(EmailVerificationCode.email == email)
        .values(created_at=EmailVerificationCode.created_at - timedelta(seconds=seconds))
    )
    db.flush()


def _signup_body(code: str, **overrides) -> dict:
    body = {
        "email": EMAIL,
        "code": code,
        "password": PASSWORD,
        "nickname": NICKNAME,
        "agreed_terms": True,
        "agreed_privacy": True,
    }
    body.update(overrides)
    return body


def _signed_up(client, outbox) -> dict:
    client.post("/api/auth/email/signup/code", json={"email": EMAIL})
    response = client.post("/api/auth/email/signup", json=_signup_body(_code_in(outbox[-1])))
    assert response.status_code == 200, response.text
    return response.json()


# ---- 가입 ----

def test_signup_creates_member_with_hashed_password(client, db, outbox):
    sent = client.post("/api/auth/email/signup/code", json={"email": EMAIL})

    assert sent.status_code == 200
    assert outbox[0]["to"] == NORMALIZED
    code = _code_in(outbox[0])
    assert client.post("/api/auth/email/signup/verify", json={"email": EMAIL, "code": code}).status_code == 200

    response = client.post("/api/auth/email/signup", json=_signup_body(code))

    assert response.status_code == 200, response.text
    assert response.json()["user"]["nickname"] == NICKNAME
    user = db.scalar(select(User).where(User.email == NORMALIZED))
    assert user.password_hash.startswith("scrypt$")
    assert PASSWORD not in user.password_hash
    # 회원·동의·구독은 한 트랜잭션 — 카카오·Apple 가입과 같은 _create_member 를 탄다.
    assert db.scalar(select(UserSubscription).where(UserSubscription.user_id == user.id)) is not None
    assert len(db.scalars(select(UserConsent).where(UserConsent.user_id == user.id)).all()) == 2


def test_code_cannot_be_used_twice(client, db, outbox):
    _signed_up(client, outbox)
    code = _code_in(outbox[-1])

    reused = client.post("/api/auth/email/signup", json=_signup_body(code))

    assert reused.status_code == 400


def test_registered_email_gets_notice_not_code_and_same_response(client, db, outbox):
    _signed_up(client, outbox)
    _age_codes(db)
    first_message = "인증 메일을 보냈어요. 메일함을 확인해주세요."

    again = client.post("/api/auth/email/signup/code", json={"email": EMAIL})

    # 응답은 미가입과 똑같다 — 가입 여부는 메일함 주인만 안다.
    assert again.status_code == 200
    assert again.json()["message"] == first_message
    assert "이미 가입된" in outbox[-1]["subject"]
    assert not re.search(r"\d{6}", outbox[-1]["subject"] + outbox[-1]["body"])


def test_wrong_code_attempts_are_capped(client, db, outbox):
    client.post("/api/auth/email/signup/code", json={"email": EMAIL})
    code = _code_in(outbox[0])
    wrong = "000000" if code != "000000" else "111111"

    for _ in range(auth_service.EMAIL_CODE_MAX_ATTEMPTS):
        response = client.post("/api/auth/email/signup/verify", json={"email": EMAIL, "code": wrong})
        assert response.json()["detail"] == auth_service.CODE_WRONG_MESSAGE

    # 한도를 넘으면 맞는 코드도 소용없다 — 대입을 끝까지 해 볼 수 없게.
    after = client.post("/api/auth/email/signup/verify", json={"email": EMAIL, "code": code})

    assert after.json()["detail"] == auth_service.CODE_EXPIRED_MESSAGE


def test_only_latest_code_is_valid(client, db, outbox):
    client.post("/api/auth/email/signup/code", json={"email": EMAIL})
    old_code = _code_in(outbox[0])
    _age_codes(db)
    client.post("/api/auth/email/signup/code", json={"email": EMAIL})
    new_code = _code_in(outbox[1])

    if old_code != new_code:
        stale = client.post("/api/auth/email/signup/verify", json={"email": EMAIL, "code": old_code})
        assert stale.status_code == 400

    assert client.post("/api/auth/email/signup/verify", json={"email": EMAIL, "code": new_code}).status_code == 200


def test_expired_code_is_rejected(client, db, outbox):
    client.post("/api/auth/email/signup/code", json={"email": EMAIL})
    db.execute(
        update(EmailVerificationCode)
        .where(EmailVerificationCode.email == NORMALIZED)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )

    response = client.post("/api/auth/email/signup/verify", json={"email": EMAIL, "code": _code_in(outbox[0])})

    assert response.json()["detail"] == auth_service.CODE_EXPIRED_MESSAGE


def test_resend_within_a_minute_is_429(client, outbox):
    client.post("/api/auth/email/signup/code", json={"email": EMAIL})

    again = client.post("/api/auth/email/signup/code", json={"email": EMAIL})

    assert again.status_code == 429
    assert len(outbox) == 1


def test_daily_cap_per_address(client, db, outbox):
    for _ in range(auth_service.EMAIL_DAILY_PER_ADDRESS):
        assert client.post("/api/auth/email/signup/code", json={"email": EMAIL}).status_code == 200
        _age_codes(db)

    capped = client.post("/api/auth/email/signup/code", json={"email": EMAIL})

    assert capped.status_code == 429


def test_mail_failure_is_503_and_leaves_no_code(client, db, monkeypatch):
    def _fail(to, subject, body):
        raise mail_client.MailUnavailableError(mail_client.UNAVAILABLE_MESSAGE)

    monkeypatch.setattr(mail_client, "send_mail", _fail)

    response = client.post("/api/auth/email/signup/code", json={"email": EMAIL})

    assert response.status_code == 503
    # 남으면 다시 누를 때 '1분에 한 번'에 걸린다.
    assert db.scalar(select(EmailVerificationCode).where(EmailVerificationCode.email == NORMALIZED)) is None


@pytest.mark.parametrize("password", ["short1", "onlyletters", "12345678", "a1" * 33])
def test_password_rule(client, outbox, password):
    client.post("/api/auth/email/signup/code", json={"email": EMAIL})

    response = client.post("/api/auth/email/signup", json=_signup_body(_code_in(outbox[0]), password=password))

    assert response.status_code == 400
    assert response.json()["detail"] == auth_service.PASSWORD_RULE_MESSAGE


def test_invalid_email_is_korean_400(client):
    response = client.post("/api/auth/email/signup/code", json={"email": "not-an-email"})

    assert response.status_code == 400
    assert response.json()["detail"] == auth_service.EMAIL_INVALID_MESSAGE


# ---- 닉네임 중복확인 ----

def _verified_code(client, outbox, email: str = EMAIL) -> str:
    client.post("/api/auth/email/signup/code", json={"email": email})
    return _code_in(outbox[-1])


def test_nickname_check_finds_existing_nickname_any_case(client, db, outbox):
    make_user(db, kakao_id="kakao-nick", nickname=" CareKim ")
    code = _verified_code(client, outbox)

    taken = client.post(
        "/api/auth/email/signup/nickname", json={"email": EMAIL, "code": code, "nickname": "carekim"}
    )
    free = client.post(
        "/api/auth/email/signup/nickname", json={"email": EMAIL, "code": code, "nickname": "새닉네임"}
    )

    assert taken.json()["detail"] == auth_service.NICKNAME_TAKEN_MESSAGE
    assert free.status_code == 200


def test_nickname_check_needs_a_valid_code(client, db, outbox):
    make_user(db, kakao_id="kakao-nick", nickname="환자김")
    code = _verified_code(client, outbox)
    wrong = "000000" if code != "000000" else "111111"

    response = client.post(
        "/api/auth/email/signup/nickname", json={"email": EMAIL, "code": wrong, "nickname": "환자김"}
    )

    # 코드 없이 물으면 닉네임 주인의 가입 여부를 답하지 않는다.
    assert response.json()["detail"] == auth_service.CODE_WRONG_MESSAGE


def test_taken_nickname_probes_burn_code_attempts(client, db, outbox):
    make_user(db, kakao_id="kakao-nick", nickname="환자김")
    code = _verified_code(client, outbox)

    for _ in range(auth_service.EMAIL_CODE_MAX_ATTEMPTS):
        client.post("/api/auth/email/signup/nickname", json={"email": EMAIL, "code": code, "nickname": "환자김"})

    after = client.post(
        "/api/auth/email/signup/nickname", json={"email": EMAIL, "code": code, "nickname": "새닉네임"}
    )

    assert after.json()["detail"] == auth_service.CODE_EXPIRED_MESSAGE


def test_signup_rejects_taken_nickname(client, db, outbox):
    make_user(db, kakao_id="kakao-nick", nickname=NICKNAME)
    code = _verified_code(client, outbox)

    response = client.post("/api/auth/email/signup", json=_signup_body(code))

    assert response.json()["detail"] == auth_service.NICKNAME_TAKEN_MESSAGE
    assert db.scalar(select(User).where(User.email == NORMALIZED)) is None


# ---- 로그인 ----

def test_login_with_any_case_email(client, outbox):
    _signed_up(client, outbox)

    response = client.post("/api/auth/email/login", json={"email": "PATIENT.KIM@example.com", "password": PASSWORD})

    assert response.status_code == 200
    assert response.json()["access_token"]


def test_login_failures_share_one_message(client, outbox):
    _signed_up(client, outbox)

    wrong_password = client.post("/api/auth/email/login", json={"email": EMAIL, "password": "wrong1234"})
    unknown_email = client.post("/api/auth/email/login", json={"email": "nobody@example.com", "password": PASSWORD})

    assert wrong_password.status_code == unknown_email.status_code == 400
    assert wrong_password.json() == unknown_email.json()


def test_lockout_blocks_even_the_right_password(client, db, outbox):
    _signed_up(client, outbox)

    for _ in range(auth_service.LOGIN_MAX_FAILURES):
        client.post("/api/auth/email/login", json={"email": EMAIL, "password": "wrong1234"})

    locked = client.post("/api/auth/email/login", json={"email": EMAIL, "password": PASSWORD})

    assert locked.status_code == 400
    assert locked.json()["detail"] == auth_service.LOGIN_FAILED_MESSAGE

    # 잠금이 풀리면 다시 들어간다.
    db.execute(
        update(User)
        .where(User.email == NORMALIZED)
        .values(login_locked_until=datetime.now(UTC) - timedelta(seconds=1))
    )
    assert client.post("/api/auth/email/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 200


# ---- 비밀번호 재설정 ----

def test_reset_for_unknown_email_sends_nothing_but_answers_the_same(client, outbox):
    response = client.post("/api/auth/email/password-reset/code", json={"email": "nobody@example.com"})

    assert response.status_code == 200
    assert response.json()["message"] == "인증 메일을 보냈어요. 메일함을 확인해주세요."
    assert outbox == []


def test_reset_changes_password_and_revokes_sessions(client, db, outbox):
    signed_up = _signed_up(client, outbox)
    _age_codes(db)
    client.post("/api/auth/email/password-reset/code", json={"email": EMAIL})
    code = _code_in(outbox[-1])

    response = client.post(
        "/api/auth/email/password-reset",
        json={"email": EMAIL, "code": code, "new_password": "newpass2026"},
    )

    assert response.status_code == 200
    user = db.scalar(select(User).where(User.email == NORMALIZED))
    assert db.scalar(select(AuthSession).where(AuthSession.user_id == user.id)).revoked_at is not None
    assert auth_service.get_user_by_session_token(db, signed_up["access_token"]) is None
    assert client.post("/api/auth/email/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 400
    assert client.post("/api/auth/email/login", json={"email": EMAIL, "password": "newpass2026"}).status_code == 200


def test_signup_code_cannot_reset_password(client, db, outbox):
    _signed_up(client, outbox)
    _age_codes(db)
    client.post("/api/auth/email/signup/code", json={"email": EMAIL})  # 이미 회원 → 안내 메일

    response = client.post(
        "/api/auth/email/password-reset",
        json={"email": EMAIL, "code": "123456", "new_password": "newpass2026"},
    )

    assert response.status_code == 400


# ---- 탈퇴 · 정리 ----

def test_delete_account_removes_email_codes(client, db, outbox):
    _signed_up(client, outbox)
    user = db.scalar(select(User).where(User.email == NORMALIZED))

    account_service.delete_account(db, user)

    assert db.scalar(select(EmailVerificationCode).where(EmailVerificationCode.email == NORMALIZED)) is None
    assert db.scalar(select(User).where(User.email == NORMALIZED)) is None


def test_purge_removes_day_old_codes(client, db, outbox):
    client.post("/api/auth/email/signup/code", json={"email": EMAIL})
    _age_codes(db, seconds=2 * 24 * 3600)

    result = auth_service.purge_expired_auth(db)

    assert result["codes"] >= 1
    assert db.scalar(select(EmailVerificationCode).where(EmailVerificationCode.email == NORMALIZED)) is None


# ---- 메일 어댑터 ----

def test_mail_refuses_plaintext_to_remote_server(monkeypatch):
    class _NoTls:
        def __init__(self, *args, **kwargs):
            self.closed = False

        def ehlo(self):
            pass

        def has_extn(self, name):
            return False

        def close(self):
            self.closed = True

    monkeypatch.setattr(mail_client, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(mail_client, "SMTP_PORT", 587)
    monkeypatch.setattr(mail_client, "SMTP_USERNAME", "sender@example.com")
    monkeypatch.setattr(mail_client, "SMTP_PASSWORD", "secret")
    monkeypatch.setattr(smtplib, "SMTP", _NoTls)

    # STARTTLS 가 없으면 로그인(비밀번호 전송) 전에 멈춘다.
    with pytest.raises(mail_client.MailUnavailableError):
        mail_client.send_mail("to@example.com", "제목", "본문")


def test_mail_without_config_is_unavailable(monkeypatch):
    monkeypatch.setattr(mail_client, "SMTP_HOST", "")

    with pytest.raises(mail_client.MailUnavailableError):
        mail_client.send_mail("to@example.com", "제목", "본문")
