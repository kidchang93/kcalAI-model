from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from database import get_db
from models.auth_model import User
from schemas.auth_schema import AuthError
from schemas.subscription_schema import (
    MySubscriptionResponse,
    PlanChangeRequest,
    PlansResponse,
)
from services.subscription_service import change_plan, list_plans_view, my_subscription_view

router = APIRouter()


@router.get("/plans", response_model=PlansResponse)
def list_available_plans(db: Session = Depends(get_db)):
    # 유일한 무인증 GET 이다 (7장의 Bearer 규약 예외). 가격표는 비밀이 아니고, 가입 화면이
    # 로그인 이전에 요금제를 그려야 한다.
    return list_plans_view(db)


@router.get(
    "/me/subscription",
    response_model=MySubscriptionResponse,
    responses={401: {"model": AuthError}},
)
def get_my_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return my_subscription_view(db, current_user.id)


@router.put(
    "/me/subscription",
    response_model=MySubscriptionResponse,
    responses={400: {"model": AuthError}, 401: {"model": AuthError}},
)
def update_my_subscription(
    request: PlanChangeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 결제 연동 전이라 이 라우트는 검증 없이 플랜을 바꾼다. 인앱결제를 붙일 때 영수증 검증
    # (App Store / Play Billing)을 통과한 뒤에만 change_plan 을 호출하도록 좁혀야 한다.
    try:
        change_plan(db, current_user.id, request.plan_code)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    return my_subscription_view(db, current_user.id)
