from datetime import date

from pydantic import BaseModel, Field


class NextVisitRequest(BaseModel):
    # 세 칸 모두 **생략 = 안 건드림**이다. 날짜를 생략하는 것은 질문부터 담는 사람 때문이다 —
    # 예정이 없으면 날짜 없는 예정 행을 만든다(2026-10-05). 셋 다 없으면 400.
    scheduled_on: date | None = None
    # 진료에서 들은 것 — 식단 지침·주의사항을 사용자가 옮겨 적는다. 빈 문자열은 지움.
    # ⚠️ 자유 텍스트라 질병 정보가 들어올 수 있어, **값이 있으면 sensitive_health 동의를
    # 요구한다**(날짜만 보낼 때는 요구하지 않는다 — `api/visit_api.py`).
    outcome: str | None = Field(default=None, max_length=1000)
    # 진료 때 물어볼 것. **줄바꿈으로 나눈 목록**이다(한 줄 = 질문 하나) — 앱이 나누고 합친다.
    # 동의·지움 규칙은 outcome 과 같다.
    questions: str | None = Field(default=None, max_length=1000)


class NextVisitResponse(BaseModel):
    # 등록된 예정이 없거나, 질문만 담고 날짜는 아직 없으면 null 이다.
    scheduled_on: date | None
    # 동의가 없으면 **null 로 내린다**(저장값은 지우지 않는다) — 날짜는 계속 보여야 D-day 가
    # 살아 있고, 민감할 수 있는 본문만 가린다. questions 도 같다.
    outcome: str | None
    questions: str | None
    # **D-day 를 서버가 계산하지 않는다.** 서버 시각은 UTC 이고 사용자는 자기 지역의 '오늘'로
    # 남은 날을 센다 — 서버가 계산하면 자정 전후로 하루가 어긋난다. 날짜만 주고 앱이 센다.
    notice: str
