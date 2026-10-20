from pydantic import BaseModel


class CitationLink(BaseModel):
    """근거 문헌의 원문 링크 (DATA_MODEL 34장). App Store 1.4.1 — 의료 정보에는 출처 링크가 있어야 한다."""

    title: str
    publisher: str
    url: str


class CitationListResponse(BaseModel):
    citations: list[CitationLink]
