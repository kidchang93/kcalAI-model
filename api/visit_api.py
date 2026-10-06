from fastapi import APIRouter

from api.dependencies import DB, CurrentUser
from schemas.visit_schema import NextVisitRequest, NextVisitResponse, PastVisit, PastVisitsResponse
from services import consent_service, visit_service
from timeutil import today_kst

router = APIRouter()

# **라우트에 `sensitive_health` 동의를 걸지 않는다.** 검사 수치(`/api/me/labs`)와 다른 판단이고,
# 근거는 **날짜**에는 질병명도 수치도 없다는 점이다. 동의를 요구하면 온보딩 직후 홈에 D-day 를
# 못 그리는데, 그러면 이 기능이 존재하는 이유(오늘 기록할 이유를 만드는 것)가 첫날부터 사라진다.
# 가이드(`/api/guides`)를 동의 없이 여는 것과 같은 층위다. 자유 텍스트인 메모 두 칸
# (`outcome`·`questions`)만 필드 단위로 동의를 요구하고, 동의가 없으면 읽을 때 가린다.
#
# ⚠️ 다만 `clinic_label`(병원 이름)을 API 로 여는 순간 이 판단을 다시 해야 한다 —
# "OO신장내과"는 질환을 추론하게 하므로 그때는 민감정보에 가깝다.

_NOTICE = (
    "진료 일정과 메모는 직접 적어 두는 기록입니다. 병원 예약과는 무관하며 저희가 병원에 "
    "전달하지 않습니다."
)


def _to_response(visit, *, can_see_memo: bool) -> NextVisitResponse:
    # 동의가 없으면(버전이 낡은 동의 포함) 메모 두 칸을 가린다. **지우지는 않는다** — 다시 동의하면
    # 그대로 보인다.
    show_memo = visit is not None and can_see_memo
    return NextVisitResponse(
        scheduled_on=visit.scheduled_on if visit is not None else None,
        outcome=visit.outcome if show_memo else None,
        questions=visit.questions if show_memo else None,
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
        can_see_memo=consent_service.has_active_consent(db, current_user.id),
    )


@router.put("/me/next-visit", response_model=NextVisitResponse)
def put_next_visit(request: NextVisitRequest, current_user: CurrentUser, db: DB):
    # **날짜만 보내면 동의가 필요 없다.** 내용이 있는 메모(outcome·questions)를 실어 보낼 때만
    # 요구한다 — 자유 텍스트라 질병 정보가 들어올 수 있기 때문이고, 반대로 날짜에까지 동의를 걸면
    # 온보딩 직후 홈 D-day 가 사라진다. 지우는 것(빈 문자열)은 동의 없이도 된다. 버전이 낡은
    # 동의도 동의가 없는 것으로 본다(require_sensitive_consent 와 같은 판정).
    if any(memo is not None and memo.strip() for memo in (request.outcome, request.questions)):
        consent_service.ensure_sensitive_consent(db, current_user.id)

    has_consent = consent_service.has_active_consent(db, current_user.id)

    visit = visit_service.set_next_visit(
        db, user_id=current_user.id, today=today_kst(), **request.model_dump()
    )
    return _to_response(visit, can_see_memo=has_consent)


@router.delete("/me/next-visit", status_code=204)
def delete_next_visit(current_user: CurrentUser, db: DB):
    """예정을 지운다. 지울 것이 없어도 204 다 — 삭제는 멱등해야 한다."""
    visit_service.clear_next_visit(db, current_user.id)


@router.get("/me/visits", response_model=PastVisitsResponse)
def list_past_visits(current_user: CurrentUser, db: DB):
    """지난 진료 목록 (DATA_MODEL 32-6). 메모 두 칸은 next-visit 과 같은 규칙으로 동의가 없으면 가린다."""
    can_see_memo = consent_service.has_active_consent(db, current_user.id)
    visits = visit_service.list_past_visits(db, current_user.id, today_kst())
    return PastVisitsResponse(
        visits=[
            PastVisit(
                visited_on=visit_service.visit_day(visit),
                questions=visit.questions if can_see_memo else None,
                outcome=visit.outcome if can_see_memo else None,
            )
            for visit in visits
        ]
    )
