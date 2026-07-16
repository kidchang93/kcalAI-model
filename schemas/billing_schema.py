from pydantic import BaseModel, Field

# 요청에 **금액이 없다**는 점이 이 계약의 핵심이다 (24장). 금액은 언제나 서버가 plans.price_krw
# 에서 정한다 — 클라이언트가 보낸 값을 받으면 100원짜리 Premium 이 팔린다.


class BillingCheckoutRequest(BaseModel):
    plan_code: str


class BillingCheckoutResponse(BaseModel):
    """결제창(토스 SDK) 초기화 값. 여기 나가는 키는 **클라이언트 키(공개값)뿐**이다 —
    시크릿 키·빌링키는 서버 밖으로 나가지 않는다.
    """

    customer_key: str
    client_key: str
    plan_code: str
    # 표시용. 실제 청구액은 confirm 에서 서버가 다시 결정한다.
    amount: int
    order_name: str


class BillingConfirmRequest(BaseModel):
    # 결제창이 성공 콜백으로 준 값. authKey 는 1회용이다.
    auth_key: str = Field(..., min_length=1, max_length=200)
    customer_key: str = Field(..., min_length=1, max_length=64)
    plan_code: str


class BillingError(BaseModel):
    detail: str
