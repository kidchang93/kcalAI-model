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


class TossWebhookEvent(BaseModel):
    """토스 웹훅 본문 (29장).

    **여기 담긴 값은 신뢰하지 않는다.** 결제 웹훅에는 서명이 없어 누구나 같은 모양의 JSON 을
    보낼 수 있다. 그래서 이 스키마의 역할은 "주문번호를 어디서 찾을지"까지이고, 상태·금액은
    서버가 토스에 다시 물어본다.

    모든 필드가 선택값인 이유: 모르는 이벤트가 와도 **422 로 거절하지 않기 위해서다.** 거절하면
    토스가 3일 19시간 동안 7번 재전송하는데, 재전송해도 결과는 같다.
    """

    event_type: str | None = Field(default=None, alias="eventType")
    data: dict | None = None
    # 일부 이벤트는 주문번호를 최상위에 둔다. 두 자리를 모두 본다.
    order_id: str | None = Field(default=None, alias="orderId")

    model_config = {"populate_by_name": True, "extra": "ignore"}

    @property
    def resolved_order_id(self) -> str | None:
        """본문 어디에 있든 주문번호 하나를 꺼낸다. 형식 검증은 하지 않는다 — 우리 원장에
        있는지가 유일한 판정이고, 그건 서비스가 한다.
        """
        if isinstance(self.data, dict):
            candidate = self.data.get("orderId")

            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()

        return self.order_id.strip() if self.order_id and self.order_id.strip() else None


class BillingWebhookAck(BaseModel):
    """웹훅 응답. **처리 결과를 담지 않는다** — 어떤 주문이 존재하고 무엇이 취소됐는지는
    무인증 호출자에게 알려 줄 정보가 아니다. 토스는 200 이면 재전송하지 않는다.
    """

    received: bool = True
