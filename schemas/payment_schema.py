from datetime import datetime

from pydantic import BaseModel

# 요금제 코드는 참조 테이블(plans)이 정본이라 Literal 로 굳히지 않는다 (subscription_schema 와 같은
# 이유 — 새 요금제 추가 시 앱·서버를 함께 배포해야 하는 결합을 만들지 않는다). status 도 마찬가지로
# 문자열로 둔다: 결제 상태값(ready|done|failed|canceled)은 결제 게이트웨이(토스) 쪽 어휘라
# 서버 릴리즈 없이 늘 수 있다.


class PaymentItem(BaseModel):
    id: int
    order_id: str
    plan_code: str
    # plans.label_ko 조회값. 요금제가 삭제됐거나 조회 실패 시 plan_code 로 폴백한다.
    plan_label: str
    amount: int
    status: str
    method: str | None
    approved_at: datetime | None
    fail_reason: str | None
    created_at: datetime


class PaymentsResponse(BaseModel):
    payments: list[PaymentItem]


class PaymentError(BaseModel):
    detail: str
