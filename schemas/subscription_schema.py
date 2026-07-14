from datetime import datetime

from pydantic import BaseModel

# 요금제 코드는 참조 테이블(plans)이 정본이라 Literal 로 굳히지 않는다 — 새 요금제를 추가할 때
# 앱·서버를 함께 배포해야 하는 결합을 만들지 않기 위해서다 (DATA_MODEL.md 10장 규칙과 같은 이유).


class PlanChangeRequest(BaseModel):
    plan_code: str


class PlanItem(BaseModel):
    code: str
    label: str
    price_krw: int
    daily_vision_quota: int
    # 본인 제외, 그룹에 추가할 수 있는 인원.
    max_group_members: int
    max_pets: int
    max_owned_groups: int


class PlansResponse(BaseModel):
    plans: list[PlanItem]


class VisionUsage(BaseModel):
    used: int
    limit: int
    remaining: int
    # 다음 리셋 시각(KST 자정을 UTC 로 표현).
    resets_at: datetime


class MySubscriptionResponse(BaseModel):
    plan: PlanItem
    vision_usage: VisionUsage
    started_at: datetime


class PlanLimitErrorResponse(BaseModel):
    """402 응답 본문. 앱은 `resource` 로 어떤 한도에 걸렸는지 구분해 업그레이드 화면을 띄운다.

    이름을 `PlanLimitError` 로 두지 않는다 — 서비스 레이어의 **예외** 클래스와 이름이 겹치면,
    이 모델을 import 한 모듈에서 `except PlanLimitError:` 를 쓰는 순간 BaseException 을 상속하지
    않았다는 TypeError 가 런타임에 터진다.
    """

    detail: str
    code: str = "plan_limit_exceeded"
    resource: str
    plan: str
    limit: int
