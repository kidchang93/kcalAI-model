from datetime import date
from typing import Literal

from pydantic import BaseModel

# 주간 조언 계약 (docs/ACTIVITY_GUIDANCE.md 3-5).
# 문구는 **서버가 만든다** — 규칙 기반이라 같은 상황이면 같은 답이고, 앱은 그리기만 한다.


class CoachingItem(BaseModel):
    # 규칙 식별자. 앱이 문구를 바꾸지 않고 로깅·분기에 쓸 수 있게 준다.
    code: str
    # good(잘하고 있음) · tip(제안) · caution(주의). 앱이 색·아이콘을 고르는 축이다.
    tone: Literal["good", "tip", "caution"]
    message: str
    # 근거 수치. 조언만 있고 근거가 없으면 사용자가 판단할 수 없다.
    evidence: str | None = None


class CoachingResponse(BaseModel):
    week_start: date
    week_end: date
    # 반영된 질병 표시명. 있으면 앱이 "○○ 반영"을 보여준다.
    conditions: list[str]
    items: list[CoachingItem]
    notice: str


class CoachingError(BaseModel):
    detail: str
