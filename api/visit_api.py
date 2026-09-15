from fastapi import APIRouter

from api.dependencies import DB, CurrentUser
from schemas.visit_schema import NextVisitRequest, NextVisitResponse
from services import consent_service, visit_service
from timeutil import today_kst

router = APIRouter()

# **`sensitive_health` 동의를 요구하지 않는다.** 검사 수치(`/api/me/labs`)와 다른 판단이고,
# 근거는 이 라우트가 다루는 값이 **날짜 하나**라는 점이다 — 질병명도 수치도 없다. 동의를
# 요구하면 온보딩 직후 홈에 D-day 를 못 그리는데, 그러면 이 기능이 존재하는 이유(오늘
# 기록할 이유를 만드는 것)가 첫날부터 사라진다. 가이드(`/api/guides`)를 동의 없이 여는 것과
# 같은 층위다.
#
# ⚠️ 다만 `clinic_label`(병원 이름)을 API 로 여는 순간 이 판단을 다시 해야 한다 —
# "OO신장내과"는 질환을 추론하게 하므로 그때는 민감정보에 가깝다.

_NOTICE = (
    "진료 일정과 메모는 직접 적어 두는 기록입니다. 병원 예약과는 무관하며 저희가 병원에 "
    "전달하지 않습니다."
)


def _to_response(visit, *, can_see_outcome: bool) -> NextVisitResponse:
    return NextVisitResponse(
        scheduled_on=visit.scheduled_on if visit is not None else None,
        # 동의가 없으면(버전이 낡은 동의 포함) 본문을 가린다. **지우지는 않는다** — 다시 동의하면
        # 그대로 보인다.
        outcome=visit.outcome if visit is not None and can_see_outcome else None,
        notice=_NOTICE,
    )


@router.get("/me/next-visit", response_model=NextVisitResponse)
def get_next_visit(current_user: CurrentUser, db: DB):
    """다음 진료 예정일. 없으면 `scheduled_on` 이 null 이다 (404 가 아니다).

    404 로 두면 앱이 "없음"과 "실패"를 구분하려고 예외 처리를 하게 된다. 등록하지 않은
    상태는 오류가 아니라 정상 상태다.
    """
    return _to_response(
        visit_service.get_next_visit(db, current_user.id),
        can_see_outcome=consent_service.has_active_consent(db, current_user.id),
    )


@router.put("/me/next-visit", response_model=NextVisitResponse)
def put_next_visit(request: NextVisitRequest, current_user: CurrentUser, db: DB):
    # **날짜만 보내면 동의가 필요 없다.** 메모를 실어 보낼 때만 요구한다 — 자유 텍스트라
    # 질병 정보가 들어올 수 있기 때문이고, 반대로 날짜에까지 동의를 걸면 온보딩 직후
    # 홈 D-day 가 사라진다. 버전이 낡은 동의도 동의가 없는 것으로 본다(require_sensitive_consent 와 같은 판정).
    if request.outcome is not None and request.outcome.strip():
        consent_service.ensure_sensitive_consent(db, current_user.id)

    has_consent = consent_service.has_active_consent(db, current_user.id)

    visit = visit_service.set_next_visit(
        db, user_id=current_user.id, today=today_kst(), **request.model_dump()
    )
    return _to_response(visit, can_see_outcome=has_consent)


@router.delete("/me/next-visit", status_code=204)
def delete_next_visit(current_user: CurrentUser, db: DB):
    """예정을 지운다. 지울 것이 없어도 204 다 — 삭제는 멱등해야 한다."""
    visit_service.clear_next_visit(db, current_user.id)
