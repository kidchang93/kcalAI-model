from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from database import get_db
from models.auth_model import User
from schemas.billing_schema import (
    BillingCheckoutRequest,
    BillingCheckoutResponse,
    BillingConfirmRequest,
    BillingError,
)
from schemas.subscription_schema import MySubscriptionResponse
from services import billing_service
from services.subscription_service import my_subscription_view
from services.toss_client import TossError, TossNotConfiguredError

router = APIRouter()

# 예외 → 상태코드 규약 (내부 예외 원문은 절대 나가지 않는다):
#   ValueError              → 400  서비스가 만든 한국어 사용자 메시지
#   TossNotConfiguredError  → 503  결제 키 미설정 (장애가 아니라 미구성)
#   TossError               → 502  결제사 오류. TossError.message 는 우리가 통제하는 한국어 문구다
_NOT_CONFIGURED_DETAIL = "결제 서비스를 준비 중입니다. 잠시 후 다시 시도해주세요."


@router.post(
    "/billing/checkout",
    response_model=BillingCheckoutResponse,
    responses={
        400: {"model": BillingError},
        401: {"model": BillingError},
        503: {"model": BillingError},
    },
)
def start_billing_checkout(
    request: BillingCheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return billing_service.start_checkout(db, current_user.id, request.plan_code)
    except TossNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_NOT_CONFIGURED_DETAIL
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.post(
    "/billing/confirm",
    response_model=MySubscriptionResponse,
    responses={
        400: {"model": BillingError},
        401: {"model": BillingError},
        502: {"model": BillingError},
        503: {"model": BillingError},
    },
)
def confirm_billing(
    request: BillingConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
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
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    return my_subscription_view(db, current_user.id)


@router.post(
    "/billing/cancel",
    response_model=MySubscriptionResponse,
    responses={400: {"model": BillingError}, 401: {"model": BillingError}},
)
def cancel_billing(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 해지는 우리 DB 상태 변경뿐이라 토스를 부르지 않는다 — 다음 청구를 하지 않는 것이 곧 해지다.
    try:
        billing_service.cancel_billing(db, current_user.id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    return my_subscription_view(db, current_user.id)
