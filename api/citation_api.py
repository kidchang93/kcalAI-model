from fastapi import APIRouter

from api.dependencies import CurrentUser
from schemas.citation_schema import CitationListResponse
from services import citations

router = APIRouter()


# 앱 '근거와 출처' 화면이 그리는 문헌 전체 (DATA_MODEL 34장). 공개 정보라 동의는 요구하지 않는다 —
# 가이드(`/api/guides`)와 같은 판단이다. 앱이 직접 쓰는 근거(계산식·식약처 DB)는 앱이 갖는다.
@router.get("/citations", response_model=CitationListResponse)
def list_citations(_: CurrentUser):
    return CitationListResponse(citations=citations.all_links())
