from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from database import get_db
from models.auth_model import User
from schemas.guide_schema import (
    ConditionGuideResponse,
    GuideListResponse,
    GuideSummary,
)
from services import meta_service, nutrition_guide

router = APIRouter()


# `sensitive_health` 동의를 요구하지 **않는다.** 이 응답은 학회 지침을 옮긴 공개 정보이고
# 사용자의 질병·검사값을 읽지 않는다 — 어떤 질환의 가이드를 볼지는 호출자가 정한다.
# 동의를 요구하면 온보딩에서 질환을 고른 직후(§CARE_LOOP 5-2의 첫 진입점)에 막히는데,
# 정작 그 순간이 사용자가 가장 알고 싶어 하는 때다.
#
# 병기별로 값이 갈리는 항목(나트륨 2,000 vs 3,000)은 **양쪽을 병기**하므로 개인화가 필요 없다.
# 개인 목표량을 계산해 주는 것은 처방에 가까워 하지 않는다 (CKD_NUTRITION §'노출 원칙').


@router.get("/guides", response_model=GuideListResponse)
def list_guides(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """가이드가 있는 질환 목록. 앱이 진입점을 그릴지 판단하는 데 쓴다.

    근거 문서가 없는 질환(임신·암)은 여기 없다 — 목록에 없으면 앱은 진입점을 그리지 않는다.

    `is_mine` 은 사용자가 등록한 질환인지다. 등록 질환을 읽지만 **동의를 요구하지는 않는다** —
    미동의면 등록된 질환이 없어 전부 false 가 되고, 목록 자체(공개 정보)는 그대로 나간다.
    """
    mine = {row.code for row in meta_service.list_user_condition_types(db, current_user.id)}
    summaries = []

    for code in nutrition_guide.available_conditions():
        guide = nutrition_guide.get_guide(code)

        if guide is None:  # pragma: no cover - available_conditions 가 보증한다
            continue

        summaries.append(
            GuideSummary(
                condition=guide.condition,
                label=guide.label,
                intro=guide.intro,
                axis_count=len(guide.axes),
                is_mine=guide.condition in mine,
            )
        )

    # 내 질환을 앞에 둔다. 홈 카드는 앞에서부터 그리므로 순서가 곧 노출 우선순위다.
    summaries.sort(key=lambda item: not item.is_mine)

    return GuideListResponse(conditions=summaries)


@router.get(
    "/guides/{condition}",
    response_model=ConditionGuideResponse,
    responses={404: {"description": "가이드가 없는 질환"}},
)
def read_guide(condition: str, _: User = Depends(get_current_user)):
    guide = nutrition_guide.get_guide(condition)

    if guide is None:
        # 없는 질환 코드와 "아직 근거를 정리하지 못한 질환"을 구분하지 않는다 — 둘 다
        # 보여줄 것이 없다는 점에서 같고, 앱은 진입점을 숨기면 된다.
        raise HTTPException(status_code=404, detail="아직 준비된 식이 가이드가 없습니다.")

    return ConditionGuideResponse(
        condition=guide.condition,
        label=guide.label,
        intro=guide.intro,
        axes=[
            {
                "axis": axis.axis,
                "label": axis.label,
                "summary": axis.summary,
                "sections": [
                    {"title": section.title, "paragraphs": list(section.paragraphs)}
                    for section in axis.sections
                ],
                "sources": list(axis.sources),
                "caution": axis.caution,
            }
            for axis in guide.axes
        ],
        notice=nutrition_guide.GUIDE_NOTICE,
    )
