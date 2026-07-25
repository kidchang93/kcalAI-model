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
# 결제 취소. paymentKey 를 경로에 싣는다 (토스 공식 문서 「결제 취소하기」).
CANCEL_PAYMENT_URL = "https://api.tosspayments.com/v1/payments"
# 결제 조회. **주문번호로** 조회한다 (토스 공식 문서 「결제 조회하기」).
# paymentKey 가 아니라 orderId 를 쓰는 이유는 웹훅 검증 때문이다 — orderId 는 우리가 만들어
# 원장(`payments.order_id`)에 갖고 있는 값이라, 외부에서 준 식별자를 믿지 않고 조회할 수 있다.
GET_PAYMENT_BY_ORDER_URL = "https://api.tosspayments.com/v1/payments/orders"

# 조회했는데 토스가 그 주문을 모를 때의 코드 (실측 2026-07-26: 404 NOT_FOUND_PAYMENT).
# 재시도해도 답이 달라지지 않는 종류라, 웹훅 동기화가 재전송을 요청하지 않고 닫는 데 쓴다.
ERROR_NOT_FOUND_PAYMENT = "NOT_FOUND_PAYMENT"

# 토스 결제 상태 (공식 문서 「결제 객체」의 status).
STATUS_DONE = "DONE"
STATUS_CANCELED = "CANCELED"
STATUS_PARTIAL_CANCELED = "PARTIAL_CANCELED"
STATUS_ABORTED = "ABORTED"
STATUS_EXPIRED = "EXPIRED"

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


def _post(url: str, payload: dict, *, action: str, idempotency_key: str | None = None) -> dict:
    """토스 POST 공통. 실패는 전부 TossError. 요청 본문·키는 로그에 남기지 않는다.

    `idempotency_key` 를 주면 `Idempotency-Key` 헤더로 보낸다 — 토스는 모든 POST 에서 이를
    지원하며 **처음 요청일로부터 15일, 최대 300자**다(공식 문서 「인증 및 기타 헤더」).
    같은 키로 다시 부르면 중복 처리되지 않으므로, **취소처럼 돈이 두 번 나가면 안 되는**
    호출에 쓴다.
    """
    headers = {"Authorization": _auth_header(), "Content-Type": "application/json"}

    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key[:300]

    try:
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=TOSS_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        # **예외 메시지에 요청 URL 이 통째로 들어간다.** charge_billing 은 토스 규격상 빌링키를
        # URL 경로에 싣기 때문에(`{CHARGE_BILLING_URL}/{billing_key}`), repr/str 을 그대로 찍으면
        # 빌링키가 평문으로 로그에 남는다 — 저장은 AES-256-GCM 으로 해 두고 로그로 흘리면 그
        # 암호화가 무의미해진다. 연결 계열 예외(ConnectionError → MaxRetryError, SSLError 등)가
        # URL 을 메시지에 담는다(read timeout 은 안 담지만 구분해 믿을 이유가 없다).
        #
        # 그래서 **예외 타입 이름만** 남긴다. action 이 어느 호출인지 알려주고 타입이 원인 범주를
        # (연결 거부·타임아웃·TLS) 알려주므로 진단에는 충분하다.
        error_logger.error(f"toss {action} request fail: {type(error).__name__}")
        # `from None` 으로 원인 체인을 끊는다 — 체인을 남기면 상위 어딘가가 트레이스백을 찍는
        # 순간(logger.exception, 미처리 예외) 같은 URL 이 그 경로로 다시 샌다.
        raise TossError("결제 서버와 통신하지 못했습니다. 잠시 후 다시 시도해주세요.") from None

    return _read_json(response, action=action)


def _get(url: str, *, action: str) -> dict:
    """토스 GET 공통. 실패 규약은 `_post` 와 같다 — URL·예외 원문을 로그에 남기지 않는다.

    조회 계열(결제 조회)에만 쓴다. 상태를 바꾸지 않으므로 멱등키가 필요 없다.
    """
    try:
        response = requests.get(
            url,
            headers={"Authorization": _auth_header()},
            timeout=TOSS_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        # `_post` 와 같은 이유로 타입 이름만 남기고 원인 체인을 끊는다 (URL 유출 방지).
        error_logger.error(f"toss {action} request fail: {type(error).__name__}")
        raise TossError("결제 서버와 통신하지 못했습니다. 잠시 후 다시 시도해주세요.") from None

    return _read_json(response, action=action)


def _read_json(response: requests.Response, *, action: str) -> dict:
    """응답 → dict. 4xx·5xx 와 비-JSON 을 전부 `TossError` 로 바꾼다."""
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

    빌링키는 토스 규격상 URL 경로에 들어간다. `_post` 는 url 을 직접 로깅하지 않을 뿐 아니라
    **요청 예외의 메시지·원인 체인도 남기지 않는다** — 둘 다 URL 을 담아 빌링키를 흘리기 때문이다
    (`tests/test_toss_client.py` 가 이 속성을 건다).
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


@dataclass(frozen=True)
class CancelResult:
    """취소 결과. `status` 는 토스 결제 상태(CANCELED / PARTIAL_CANCELED)다."""

    status: str
    canceled_amount: int
    canceled_at: datetime | None


def cancel_payment(
    payment_key: str,
    reason: str,
    *,
    amount: int | None = None,
    idempotency_key: str | None = None,
) -> CancelResult:
    """결제를 취소한다. `amount` 를 주면 부분 취소, 없으면 전액이다.

    토스 규격 (공식 문서 「결제 취소하기」):
        POST /v1/payments/{paymentKey}/cancel
        cancelReason 필수 · cancelAmount 선택(미입력 시 전액) · 응답에 cancels 배열

    ⚠️ **호출 전에 우리 원장 상태를 먼저 확인한다** (`billing_service.refund_payment`).
    이미 취소된 결제를 다시 부르면 토스가 거부하지만, 그 전에 우리가 막는 편이 낫다 —
    돈이 두 번 나가는 종류의 실수는 사후에 알아채면 늦다. 멱등키는 그 위의 마지막 방어선이다.
    """
    ensure_configured()

    payload: dict[str, object] = {"cancelReason": reason}

    if amount is not None:
        payload["cancelAmount"] = amount

    response = _post(
        f"{CANCEL_PAYMENT_URL}/{payment_key}/cancel",
        payload,
        action="cancel payment",
        idempotency_key=idempotency_key,
    )

    cancels = response.get("cancels") or []
    latest = cancels[-1] if isinstance(cancels, list) and cancels else {}

    return CancelResult(
        status=str(response.get("status", "")),
        # 응답의 취소 금액을 그대로 쓴다 — 우리가 보낸 값이 아니라 **실제로 취소된 금액**이
        # 원장에 남아야 한다.
        canceled_amount=int(latest.get("cancelAmount") or amount or 0),
        canceled_at=_parse_approved_at(latest.get("canceledAt")),
    )


@dataclass(frozen=True)
class PaymentSnapshot:
    """토스가 말하는 **지금** 이 결제의 상태. 웹훅 동기화의 유일한 근거다 (29장).

    `canceled_amount` 는 `cancels` 배열을 더하지 않고 **`totalAmount - balanceAmount`** 로 얻는다.
    잔액은 토스가 관리하는 값이라 부분 취소가 여러 번이어도 누계가 어긋나지 않는다.
    """

    order_id: str
    payment_key: str | None
    status: str
    total_amount: int
    balance_amount: int
    method: str | None
    approved_at: datetime | None
    canceled_amount: int
    canceled_at: datetime | None
    cancel_reason: str | None

    @property
    def is_canceled(self) -> bool:
        return self.status in (STATUS_CANCELED, STATUS_PARTIAL_CANCELED)

    @property
    def is_done(self) -> bool:
        return self.status == STATUS_DONE

    @property
    def is_dead(self) -> bool:
        """승인되지 못하고 끝난 결제 — 다시 살아나지 않는다."""
        return self.status in (STATUS_ABORTED, STATUS_EXPIRED)


def get_payment_by_order_id(order_id: str) -> PaymentSnapshot:
    """주문번호로 결제를 조회한다 (`GET /v1/payments/orders/{orderId}`).

    **웹훅을 신뢰하지 않기 위한 함수다.** 결제 웹훅에는 서명 헤더가 붙지 않으므로
    (`tosspayments-webhook-signature` 는 지급대행·셀러 이벤트 전용), 본문만 보고 원장을 고치면
    누구나 "취소됐다"고 우리 서버에 알릴 수 있다. 그래서 웹훅은 알림으로만 쓰고, 실제 상태는
    **우리 시크릿 키로 인증한 이 조회**로 확인한다 — 위조할 수 없는 경로다.
    """
    ensure_configured()
    payload = _get(f"{GET_PAYMENT_BY_ORDER_URL}/{order_id}", action="get payment")

    total_amount = _as_int(payload.get("totalAmount"))
    balance_amount = _as_int(payload.get("balanceAmount"))
    cancels = payload.get("cancels") or []
    latest_cancel = cancels[-1] if isinstance(cancels, list) and cancels else {}

    return PaymentSnapshot(
        # 응답의 orderId 를 그대로 쓰지 않고 우리가 조회에 쓴 값을 남긴다 — 이 스냅샷이 어느
        # 원장 행의 것인지가 호출자의 입력과 어긋나지 않아야 한다.
        order_id=order_id,
        payment_key=_as_text(payload.get("paymentKey")),
        status=str(payload.get("status", "")),
        total_amount=total_amount,
        balance_amount=balance_amount,
        method=_as_text(payload.get("method")),
        approved_at=_parse_approved_at(payload.get("approvedAt")),
        # 음수가 되지 않게 막는다. 잔액이 총액보다 크게 오는 일은 없지만, 그 값이 원장의
        # refunded_amount 로 들어가면 "마이너스 환불"이라는 읽을 수 없는 기록이 남는다.
        canceled_amount=max(total_amount - balance_amount, 0),
        canceled_at=_parse_approved_at(latest_cancel.get("canceledAt")),
        cancel_reason=_as_text(latest_cancel.get("cancelReason")),
    )


def _as_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _as_text(value: object) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text or None
