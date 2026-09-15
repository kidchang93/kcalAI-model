from fastapi import APIRouter, HTTPException, status

from api.dependencies import DB, CurrentUser
from log_utils import get_logger
from schemas.billing_schema import (
    BillingCheckoutRequest,
    BillingCheckoutResponse,
    BillingConfirmRequest,
    BillingWebhookAck,
    TossWebhookEvent,
)
from schemas.common_schema import ErrorResponse
from schemas.subscription_schema import MySubscriptionResponse
from services import billing_service
from services.subscription_service import my_subscription_view
from services.toss_client import TossError, TossNotConfiguredError

router = APIRouter()

logger = get_logger(__name__)

# 예외 → 상태코드 규약 (내부 예외 원문은 절대 나가지 않는다):
#   BadRequestError         → 400  서비스가 만든 한국어 사용자 메시지 (main.py 전역 핸들러)
#   TossNotConfiguredError  → 503  결제 키 미설정 (장애가 아니라 미구성)
#   TossError               → 502  결제사 오류. TossError.message 는 우리가 통제하는 한국어 문구다
_NOT_CONFIGURED_DETAIL = "결제 서비스를 준비 중입니다. 잠시 후 다시 시도해주세요."


@router.post(
    "/billing/checkout",
    response_model=BillingCheckoutResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def start_billing_checkout(request: BillingCheckoutRequest, current_user: CurrentUser, db: DB):
    try:
        return billing_service.start_checkout(db, current_user.id, request.plan_code)
    except TossNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_NOT_CONFIGURED_DETAIL
        ) from error


@router.post(
    "/billing/confirm",
    response_model=MySubscriptionResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def confirm_billing(request: BillingConfirmRequest, current_user: CurrentUser, db: DB):
    try:
        billing_service.confirm_billing(
            db,
            current_user.id,
            request.auth_key,
            request.customer_key,
            request.plan_code,
        )
    except TossNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_NOT_CONFIGURED_DETAIL
        ) from error
    except TossError as error:
        # 502: 우리 서버가 아니라 결제사 쪽 실패다. 결제 실패 원장(payments.failed)은 이미 남았다.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=error.message
        ) from error

    return my_subscription_view(db, current_user.id)


@router.post(
    "/billing/webhook",
    response_model=BillingWebhookAck,
    responses={502: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def receive_billing_webhook(request: TossWebhookEvent, db: DB):
    """토스 결제 상태 변경 알림 (DATA_MODEL.md 29장).

    **무인증이다** — 토스가 우리 Bearer 토큰을 가질 수 없다. 대신 본문을 믿지 않는 것으로
    막는다: 여기서 쓰는 값은 `orderId` 하나뿐이고, 그것도 **우리 원장에 있는 주문**일 때만
    서비스가 토스에 실제 상태를 다시 물어본다. 위조 본문으로는 원장을 바꿀 수 없다.

    상태코드의 의미가 곧 재전송 정책이다 (토스는 200 이 아니면 최대 7회, 3일 19시간 재전송):
      200 — 처리했거나, 처리할 것이 없다(모르는 주문·모르는 이벤트). 재전송 불필요.
      502·503 — 토스 조회에 실패해 **아직 판단하지 못했다.** 재전송받아 다시 시도한다.
    """
    if request.event_type not in billing_service.HANDLED_WEBHOOK_EVENTS:
        logger.info(f"webhook ignored event_type={request.event_type}")
        return BillingWebhookAck()

    order_id = request.resolved_order_id

    if order_id is None:
        logger.info(f"webhook ignored(no orderId) event_type={request.event_type}")
        return BillingWebhookAck()

    try:
        result = billing_service.sync_payment_from_toss(db, order_id)
    except TossNotConfiguredError as error:
        # 키가 없어 조회 자체를 못 했다. 재전송받는 편이 낫다 — 이 알림을 흘리면 원장이
        # 영원히 어긋난 채 남는다.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_NOT_CONFIGURED_DETAIL
        ) from error
    except TossError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=error.message
        ) from error

    logger.info(f"webhook handled event_type={request.event_type} result={result}")
    # 응답에는 결과를 싣지 않는다 — 무인증 호출자에게 주문의 존재 여부를 알려 주지 않는다.
    return BillingWebhookAck()


@router.post(
    "/billing/cancel",
    response_model=MySubscriptionResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
def cancel_billing(current_user: CurrentUser, db: DB):
    # 해지는 우리 DB 상태 변경뿐이라 토스를 부르지 않는다 — 다음 청구를 하지 않는 것이 곧 해지다.
    billing_service.cancel_billing(db, current_user.id)
    return my_subscription_view(db, current_user.id)
