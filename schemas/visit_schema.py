from datetime import date

from pydantic import BaseModel, Field


class NextVisitRequest(BaseModel):
    scheduled_on: date
    # 진료에서 들은 것 — 식단 지침·주의사항을 사용자가 옮겨 적는다. 생략하면 기존 값을 둔다.
    # ⚠️ 자유 텍스트라 질병 정보가 들어올 수 있어, **값이 있으면 sensitive_health 동의를
    # 요구한다**(날짜만 보낼 때는 요구하지 않는다 — `api/visit_api.py`).
    outcome: str | None = Field(default=None, max_length=1000)


class NextVisitResponse(BaseModel):
    # 등록된 예정이 없으면 null 이다. 앱은 그때 "진료일을 등록하세요"를 그린다.
    scheduled_on: date | None
    # 동의가 없으면 **null 로 내린다**(저장값은 지우지 않는다) — 날짜는 계속 보여야 D-day 가
    # 살아 있고, 민감할 수 있는 본문만 가린다.
    outcome: str | None
    # **D-day 를 서버가 계산하지 않는다.** 서버 시각은 UTC 이고 사용자는 자기 지역의 '오늘'로
    # 남은 날을 센다 — 서버가 계산하면 자정 전후로 하루가 어긋난다. 날짜만 주고 앱이 센다.
    notice: str
