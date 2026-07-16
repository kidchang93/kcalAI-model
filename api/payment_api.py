from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from database import get_db
from models.auth_model import User
from schemas.payment_schema import PaymentError, PaymentItem, PaymentsResponse
from services import payment_service

router = APIRouter()


@router.get(
    "/payments",
    response_model=PaymentsResponse,
    responses={401: {"model": PaymentError}},
)
def list_my_payments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return payment_service.list_payments_view(db, current_user.id)


@router.get(
    "/payments/{payment_id}",
    response_model=PaymentItem,
    responses={401: {"model": PaymentError}, 404: {"model": PaymentError}},
)
def get_my_payment(
    payment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return payment_service.get_payment_view(db, current_user.id, payment_id)
    except LookupError as error:
        # LookupError 의 메시지는 서비스가 만든 한국어 사용자 메시지라 그대로 노출해도 안전하다
        # (내부 예외 str(e) 노출 금지는 라이브러리 예외에 대한 규칙이다).
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
