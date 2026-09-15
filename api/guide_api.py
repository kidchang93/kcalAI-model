from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from api.dependencies import DB, CurrentUser
from schemas.guide_schema import (
    ConditionGuideResponse,
    GuideListResponse,
    GuideSummary,
)
from services import guide_service, nutrition_guide

router = APIRouter()


# `sensitive_health` 동의를 요구하지 **않는다.** 이 응답은 학회 지침을 옮긴 공개 정보이고
# 사용자의 질병·검사값을 읽지 않는다 — 어떤 질환의 가이드를 볼지는 호출자가 정한다.
# (목록의 `is_mine` 만 등록 질환을 읽고, 그 판정은 서비스가 동의 상태를 보고 한다.)
# 동의를 요구하면 온보딩에서 질환을 고른 직후(§CARE_LOOP 5-2의 첫 진입점)에 막히는데,
# 정작 그 순간이 사용자가 가장 알고 싶어 하는 때다.
#
# 병기별로 값이 갈리는 항목(나트륨 2,000 vs 3,000)은 **양쪽을 병기**하므로 개인화가 필요 없다.
# 개인 목표량을 계산해 주는 것은 처방에 가까워 하지 않는다 (CKD_NUTRITION §'노출 원칙').


@router.get("/guides", response_model=GuideListResponse)
def list_guides(current_user: CurrentUser, db: DB):
    """가이드가 있는 질환 목록. 앱이 진입점을 그릴지 판단하는 데 쓴다.

    근거 문서가 없는 질환(임신·암)은 여기 없다 — 목록에 없으면 앱은 진입점을 그리지 않는다.

    `is_mine` 은 사용자가 등록한 질환인지다. 라우트는 **동의를 요구하지 않는다** — 목록 자체는
    공개 정보다. 대신 서비스가 민감정보 동의가 ACTIVE 일 때만 질병을 읽고, 아니면 전부 false 다
    (`services/guide_service.py`).
    """
    summaries = guide_service.list_guide_summaries(db, current_user.id)

    return GuideListResponse(conditions=[GuideSummary(**summary) for summary in summaries])


@router.get(
    "/guides/{condition}",
    response_model=ConditionGuideResponse,
    responses={404: {"description": "가이드가 없는 질환"}},
)
def read_guide(condition: str, _: CurrentUser):
    guide = nutrition_guide.get_guide(condition)

    if guide is None:
        # 없는 질환 코드와 "아직 근거를 정리하지 못한 질환"을 구분하지 않는다 — 둘 다
        # 보여줄 것이 없다는 점에서 같고, 앱은 진입점을 숨기면 된다.
        raise HTTPException(status_code=404, detail="아직 준비된 식이 가이드가 없습니다.")

    # asdict 는 중첩 dataclass 까지 dict 로 풀고, tuple 필드는 스키마의 list[...] 로 검증된다.
    return ConditionGuideResponse(**asdict(guide), notice=nutrition_guide.GUIDE_NOTICE)
