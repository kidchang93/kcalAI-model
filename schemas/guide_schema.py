from pydantic import BaseModel


class GuideSectionResponse(BaseModel):
    title: str
    paragraphs: list[str]


class GuideAxisResponse(BaseModel):
    axis: str
    label: str
    summary: str
    sections: list[GuideSectionResponse]
    # 출처. **앱이 이 목록을 숨기면 안 된다** — 근거를 밝히는 것이 이 화면의 존재 이유이고,
    # Apple 1.4.1 이 의료 앱에 요구하는 "근거·방법론 공개"이기도 하다 (LEGAL_COMPLIANCE §6-1).
    sources: list[str]
    # 병존 질환에서 방향이 엇갈리는 축의 경고 (칼륨). 없으면 null.
    caution: str | None


class ConditionGuideResponse(BaseModel):
    condition: str
    label: str
    intro: str
    axes: list[GuideAxisResponse]
    # 전 질환 공통 고지. 서버가 문구를 정한다 — 앱이 임의로 바꾸거나 빼지 않는다.
    notice: str


class GuideSummary(BaseModel):
    condition: str
    label: str
    intro: str
    axis_count: int
    # 이 사용자가 등록한 질환인가. 홈이 "내 질환"만 카드로 그리는 데 쓴다 —
    # 이 필드가 없으면 앱이 `/api/me/conditions` 를 한 번 더 불러 교집합을 내야 한다.
    is_mine: bool


class GuideListResponse(BaseModel):
    conditions: list[GuideSummary]
