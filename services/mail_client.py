"""메일 발송 어댑터 — 이메일 가입·비밀번호 재설정의 인증 코드 (DATA_MODEL.md 21장 '이메일 가입').

표준 SMTP 하나만 쓴다(stdlib `smtplib`). 운영은 고객문의 메일과 같은 네이버 메일의 SMTP 다 —
비용이 없고 국내 사업자라 국외 이전 고지가 필요 없다(처리방침 5장 위탁). 다른 곳으로 옮길 때는
환경변수만 바꾼다.

- 465 는 처음부터 TLS(SMTPS), 그 밖의 포트는 STARTTLS 가 **필수**다. 서버가 STARTTLS 를 내리지
  않으면 보내지 않는다 — 평문으로 떨어지면 인증 코드와 SMTP 비밀번호가 그대로 흐른다.
  평문은 개발용 로컬 메일 서버(localhost, 예: mailpit)에만 허용한다.
- 설정이 없으면 `MailUnavailableError` 다(api 가 503). 카카오·Apple 은 그대로 쓸 수 있으므로
  운영 기동을 막지 않는다.
"""

import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from log_utils import get_logger


logger = get_logger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
# 비밀값. 네이버는 2단계 인증을 쓰면 '애플리케이션 비밀번호'를 넣는다.
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
# 네이버 SMTP 는 로그인 계정과 보낸 사람 주소가 같아야 받아 준다. 비우면 로그인 계정을 쓴다.
MAIL_FROM = os.getenv("MAIL_FROM", "") or SMTP_USERNAME
MAIL_FROM_NAME = "케어테이블"

SMTP_TIMEOUT_SECONDS = 10
_LOCAL_HOSTS = {"localhost", "127.0.0.1"}

UNAVAILABLE_MESSAGE = "인증 메일을 지금 보낼 수 없어요. 잠시 후 다시 시도해주세요."


class MailUnavailableError(Exception):
    """설정 없음·SMTP 장애. 메시지는 사용자용 한국어다(api 가 503 으로 바꾼다)."""


def send_mail(to: str, subject: str, body: str) -> None:
    if not (SMTP_HOST and SMTP_USERNAME and SMTP_PASSWORD):
        logger.error("mail not configured: SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD")
        raise MailUnavailableError(UNAVAILABLE_MESSAGE)

    message = EmailMessage()
    message["From"] = formataddr((MAIL_FROM_NAME, MAIL_FROM))
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        with _connect() as smtp:
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as error:
        # 받는 주소·본문(인증 코드)은 남기지 않는다. 예외 타입과 SMTP 응답 코드면 원인을 가를 수 있다.
        logger.error(f"mail send fail: {type(error).__name__} {getattr(error, 'smtp_code', '')}")
        raise MailUnavailableError(UNAVAILABLE_MESSAGE) from error


def _connect() -> smtplib.SMTP:
    context = ssl.create_default_context()

    if SMTP_PORT == 465:
        return smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS, context=context)

    smtp = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS)
    smtp.ehlo()

    if smtp.has_extn("starttls"):
        smtp.starttls(context=context)
        smtp.ehlo()
    elif SMTP_HOST not in _LOCAL_HOSTS:
        smtp.close()
        raise smtplib.SMTPNotSupportedError("STARTTLS 를 지원하지 않는 SMTP 서버")

    return smtp
