from datetime import date, datetime

from pydantic import BaseModel, Field


class LabResultRequest(BaseModel):
    measured_on: date
    panel: str = Field(..., max_length=30)
    value: float = Field(..., gt=0)
    note: str | None = Field(default=None, max_length=200)
    # 단위는 받지 않는다 — 서버가 panel 별로 정한다. 사용자가 고르면 mg/dL 과 mmol/L 이
    # 섞여 추이가 무의미해진다 (`services/lab_panels.py`).


class LabResultResponse(BaseModel):
    id: int
    measured_on: date
    panel: str
    # 표시명·단위·정상범위를 함께 싣는다. 앱이 의학 용어와 수치를 갖지 않게 하기 위해서다
    # (`ckd_stages`·운동 종류와 같은 규약).
    label: str
    value: float
    unit: str
    # 지침이 정한 정상범위·목표 문장. 근거가 없는 항목(혈압)은 null 이다.
    reference: str | None
    source_note: str
    note: str | None
    created_at: datetime


class LabResultListResponse(BaseModel):
    results: list[LabResultResponse]
    notice: str


class LabPanelOption(BaseModel):
    code: str
    label: str
    unit: str
    reference: str | None
    source: str
    conditions: list[str]
    decimals: int
    # 이 사용자의 질환에 해당하는 항목인가. 앱이 관련 항목을 앞에 두는 데 쓴다.
    is_mine: bool


class LabPanelListResponse(BaseModel):
    panels: list[LabPanelOption]
    notice: str
