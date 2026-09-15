from fastapi import APIRouter

from api.dependencies import DB, CurrentUser
from schemas.common_schema import ErrorResponse
from schemas.payment_schema import PaymentItem, PaymentsResponse
from services import payment_service

router = APIRouter()


@router.get(
    "/payments",
    response_model=PaymentsResponse,
    responses={401: {"model": ErrorResponse}},
)
def list_my_payments(current_user: CurrentUser, db: DB):
    return payment_service.list_payments_view(db, current_user.id)


@router.get(
    "/payments/{payment_id}",
    response_model=PaymentItem,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_my_payment(payment_id: int, current_user: CurrentUser, db: DB):
    return payment_service.get_payment_view(db, current_user.id, payment_id)
