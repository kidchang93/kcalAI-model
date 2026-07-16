"""토스페이먼츠 자동결제(빌링) 어댑터 — 빌링키 발급 · 빌링키 청구.

**시크릿 키와 빌링키는 서버 전용이다.** `TOSS_SECRET_KEY` 는 이 값만으로 임의 청구가 가능하고,
`billingKey` 는 그 회원의 카드를 다시 긁을 수 있는 자격증명이다. 둘 다 로그·응답·예외 메시지에
절대 남기지 않는다 — 실패는 토스 **에러 코드**와 상태코드만 남긴다 (카카오 어댑터와 같은 규약).

인증은 Basic `base64("{시크릿}:")` 이다 (비밀번호 없이 콜론까지만). 토스 문서의 규격이라
`requests` 의 auth 헬퍼 대신 직접 만든다.

실패는 전부 `TossError` 로 감싸 올린다 — 서비스·api 는 토스 응답 형태를 몰라도 된다.
`TossError.message` 는 **사용자에게 보여줄 한국어 메시지**이고(토스 원문이 아니다),
`TossError.code` 는 결제사 코드(원장 `payments.fail_code` 에만 저장, 응답에는 안 나간다).
"""

import base64
import logging
import os
from dataclasses import dataclass
from datetime import datetime

import requests

from log_utils import setup_level_logger

error_logger = setup_level_logger(logging.ERROR)

# 비밀값. 이 키 하나로 임의 금액을 청구할 수 있다 — 앱에 내려보내지 않는다.
TOSS_SECRET_KEY = os.getenv("TOSS_SECRET_KEY", "")
# 공개값. 결제창 SDK 초기화에 쓰이므로 앱에 내려준다 (checkout 응답).
TOSS_CLIENT_KEY = os.getenv("TOSS_CLIENT_KEY", "")
TOSS_TIMEOUT_SECONDS = float(os.getenv("TOSS_TIMEOUT_SECONDS", "10"))

ISSUE_BILLING_KEY_URL = "https://api.tosspayments.com/v1/billing/authorizations/issue"
CHARGE_BILLING_URL = "https://api.tosspayments.com/v1/billing"

# 토스 결제 실패 코드 → 사용자용 한국어 메시지. 토스 원문 메시지를 그대로 쓰지 않는 이유는,
# 결제사 문구가 내부 사정(가맹점 설정·API 규격)을 담을 수 있고 우리가 통제할 수 없기 때문이다.
# 원문은 error_logger 에만 남긴다.
_FAIL_MESSAGES = {
    "INVALID_CARD_NUMBER": "카드 정보가 올바르지 않습니다. 카드를 다시 등록해주세요.",
    "INVALID_CARD_EXPIRATION": "카드 유효기간이 올바르지 않습니다. 카드를 다시 등록해주세요.",
    "INVALID_STOPPED_CARD": "정지된 카드입니다. 다른 카드로 등록해주세요.",
    "EXCEED_MAX_DAILY_PAYMENT_COUNT": "카드사 일일 결제 한도를 초과했습니다. 잠시 후 다시 시도해주세요.",
    "EXCEED_MAX_ONE_DAY_AMOUNT": "카드사 일일 결제 한도를 초과했습니다. 잠시 후 다시 시도해주세요.",
    "EXCEED_MAX_AMOUNT": "카드 결제 한도를 초과했습니다.",
    "NOT_ENOUGH_BALANCE": "카드 잔액이 부족합니다.",
    "REJECT_CARD_COMPANY": "카드사에서 결제를 거절했습니다. 카드사에 문의해주세요.",
    "REJECT_ACCOUNT_PAYMENT": "카드사에서 결제를 거절했습니다. 카드사에 문의해주세요.",
    "INVALID_AUTHORIZE_AUTH": "카드 인증에 실패했습니다. 다시 시도해주세요.",
    "NOT_FOUND_PAYMENT_SESSION": "결제 시간이 만료되었습니다. 다시 시도해주세요.",
    "NOT_REGISTERED_BUSINESS": "결제 설정에 문제가 있습니다. 잠시 후 다시 시도해주세요.",
    "UNAUTHORIZED_KEY": "결제 설정에 문제가 있습니다. 잠시 후 다시 시도해주세요.",
}
_DEFAULT_FAIL_MESSAGE = "결제에 실패했습니다. 잠시 후 다시 시도해주세요."


class TossError(Exception):
    """토스 연동 실패. api 레이어가 **502**(결제사 오류)로 변환한다.

    `message` 는 사용자용 한국어 메시지, `code` 는 결제사 코드다. 코드는 원장(`fail_code`)과
    로그에만 쓰고 응답에는 내보내지 않는다.
    """

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class TossNotConfiguredError(TossError):
    """결제 키 미설정. api 레이어가 **503**으로 변환한다 (장애가 아니라 미구성이다)."""


@dataclass(frozen=True)
class IssuedBillingKey:
    billing_key: str
    card_company: str | None
    card_number: str | None
    card_type: str | None


@dataclass(frozen=True)
class ChargeResult:
    payment_key: str
    status: str
    method: str | None
    approved_at: datetime | None


def is_configured() -> bool:
    return bool(TOSS_SECRET_KEY and TOSS_CLIENT_KEY)


def ensure_production_toss_config() -> None:
    # APP_ENV=production 기동 시 main.py 가 호출한다. 키가 없으면 유료 요금제를 팔 수 없는데,
    # 그 사실이 배포 후 사용자 결제 시도에서야 드러나면 안 된다.
    if not TOSS_SECRET_KEY:
        raise RuntimeError("APP_ENV=production에서는 TOSS_SECRET_KEY가 필요합니다.")

    if not TOSS_CLIENT_KEY:
        raise RuntimeError("APP_ENV=production에서는 TOSS_CLIENT_KEY가 필요합니다.")


def ensure_configured() -> None:
    """키 미설정이면 TossNotConfiguredError. 호출 경로(결제창 준비·발급·청구)마다 부른다."""
    if not is_configured():
        raise TossNotConfiguredError("결제 서비스를 준비 중입니다. 잠시 후 다시 시도해주세요.")


def _auth_header() -> str:
    # 토스 규격: base64("{시크릿키}:") — 비밀번호 없는 Basic 인증이라 콜론까지만 인코딩한다.
    token = base64.b64encode(f"{TOSS_SECRET_KEY}:".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _post(url: str, payload: dict, *, action: str) -> dict:
    """토스 POST 공통. 실패는 전부 TossError. 요청 본문·키는 로그에 남기지 않는다."""
    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Authorization": _auth_header(), "Content-Type": "application/json"},
            timeout=TOSS_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        # 예외 객체에 URL 은 있어도 헤더(시크릿)는 없다. 그래도 repr 은 타입·메시지만 쓴다.
        error_logger.error(f"toss {action} request fail: {error!r}")
        raise TossError("결제 서버와 통신하지 못했습니다. 잠시 후 다시 시도해주세요.") from error

    if response.status_code >= 400:
        code, raw_message = _read_error(response)
        # 원문은 서버에만 남긴다. 사용자에게는 우리가 통제하는 메시지를 준다.
        error_logger.error(
            f"toss {action} fail status={response.status_code} code={code} message={raw_message}"
        )
        raise TossError(_FAIL_MESSAGES.get(code or "", _DEFAULT_FAIL_MESSAGE), code=code)

    try:
        return response.json()
    except ValueError as error:
        error_logger.error(f"toss {action} returned non-json status={response.status_code}")
        raise TossError(_DEFAULT_FAIL_MESSAGE) from error


def _read_error(response: requests.Response) -> tuple[str | None, str]:
    try:
        payload = response.json()
    except ValueError:
        return None, ""

    if not isinstance(payload, dict):
        return None, ""

    return payload.get("code"), str(payload.get("message", ""))


def _parse_approved_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None

    try:
        # 토스는 ISO8601 오프셋 표기(+09:00)를 준다. Z 표기는 3.10 fromisoformat 이 못 읽어 치환한다.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        error_logger.error("toss approvedAt 파싱 실패")
        return None


def issue_billing_key(auth_key: str, customer_key: str) -> IssuedBillingKey:
    """결제창이 준 authKey → 빌링키. 반환값의 `billing_key` 는 **암호화 저장 대상**이다."""
    ensure_configured()
    payload = _post(
        ISSUE_BILLING_KEY_URL,
        {"authKey": auth_key, "customerKey": customer_key},
        action="issue billing key",
    )
    billing_key = payload.get("billingKey")

    if not billing_key:
        error_logger.error("toss issue billing key returned no billingKey")
        raise TossError("카드 등록에 실패했습니다. 다시 시도해주세요.")

    card = payload.get("card") or {}
    return IssuedBillingKey(
        billing_key=str(billing_key),
        card_company=_as_text(card.get("company") or card.get("issuerCode")),
        # 토스가 마스킹해서 준다(앞6·뒤4). 우리가 평문 카드번호를 받는 일은 없다.
        card_number=_as_text(card.get("number")),
        card_type=_as_text(card.get("cardType")),
    )


def charge_billing(
    billing_key: str, customer_key: str, amount: int, order_id: str, order_name: str
) -> ChargeResult:
    """빌링키로 자동청구. `amount` 는 **서버가 plans.price_krw 에서 정한 값**이어야 한다.

    빌링키는 URL 경로에 들어가지만 로그에는 남기지 않는다 (`_post` 는 url 을 로깅하지 않는다).
    """
    ensure_configured()
    payload = _post(
        f"{CHARGE_BILLING_URL}/{billing_key}",
        {
            "customerKey": customer_key,
            "amount": amount,
            "orderId": order_id,
            "orderName": order_name,
        },
        action="charge billing",
    )
    payment_key = payload.get("paymentKey")

    if not payment_key:
        error_logger.error("toss charge returned no paymentKey")
        raise TossError(_DEFAULT_FAIL_MESSAGE)

    return ChargeResult(
        payment_key=str(payment_key),
        status=str(payload.get("status", "")),
        method=_as_text(payload.get("method")),
        approved_at=_parse_approved_at(payload.get("approvedAt")),
    )


def _as_text(value: object) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text or None
