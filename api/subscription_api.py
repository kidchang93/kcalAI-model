from fastapi import APIRouter

from api.dependencies import DB, CurrentUser
from schemas.common_schema import ErrorResponse
from schemas.subscription_schema import (
    MySubscriptionResponse,
    PlanChangeRequest,
    PlansResponse,
)
from services.subscription_service import change_plan, list_plans_view, my_subscription_view

router = APIRouter()


@router.get("/plans", response_model=PlansResponse)
def list_available_plans(db: DB):
    # 유일한 무인증 GET 이다 (7장의 Bearer 규약 예외). 가격표는 비밀이 아니고, 가입 화면이
    # 로그인 이전에 요금제를 그려야 한다.
    return list_plans_view(db)


@router.get(
    "/me/subscription",
    response_model=MySubscriptionResponse,
    responses={401: {"model": ErrorResponse}},
)
def get_my_subscription(current_user: CurrentUser, db: DB):
    return my_subscription_view(db, current_user.id)


@router.put(
    "/me/subscription",
    response_model=MySubscriptionResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
def update_my_subscription(request: PlanChangeRequest, current_user: CurrentUser, db: DB):
    # 결제 연동 전이라 이 라우트는 검증 없이 플랜을 바꾼다. 인앱결제를 붙일 때 영수증 검증
    # (App Store / Play Billing)을 통과한 뒤에만 change_plan 을 호출하도록 좁혀야 한다.
    change_plan(db, current_user.id, request.plan_code)
    return my_subscription_view(db, current_user.id)
