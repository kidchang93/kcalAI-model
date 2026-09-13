"""가이드 목록에 사용자 맥락(`is_mine`)을 얹는다.

가이드 본문(`services/nutrition_guide.py`)은 학회 지침을 옮긴 공개 정보라 사용자를 읽지 않는다 —
그 모듈의 원칙이다. 반면 "이 질환이 내 것인가"는 **등록 질환(민감정보)을 읽어야** 답할 수 있어,
그 조회와 동의 판정을 여기로 분리했다. 예전에는 라우트(`api/guide_api.py`)가 질병을 직접 읽었다.
"""

from sqlalchemy.orm import Session

from services import consent_service, meta_service, nutrition_guide


def list_guide_summaries(db: Session, user_id: int) -> list[dict]:
    """가이드가 있는 질환 목록. 내 질환을 앞에 둔다.

    **질병은 민감정보 동의가 ACTIVE 일 때만 읽는다** (DATA_MODEL 7장). 아니면 `is_mine` 이 전부
    false 이고 순서는 가이드 기본 순서다. 라우트를 막지 않는 이유는 목록 자체가 공개 정보라서다 —
    온보딩에서 질환을 고른 직후가 사용자가 가이드를 가장 보고 싶어 하는 때다.

    예전 주석은 "미동의면 등록된 질환이 없어 전부 false"라고 기댔다. 낡은 동의(v1.0)는 **질환을
    가진 채 무효**라 그 전제가 깨진다 — 없어서가 아니라 읽지 않아서 false 여야 한다.
    """
    mine: set[str] = set()

    if consent_service.has_active_consent(db, user_id):
        mine = {row.code for row in meta_service.list_user_condition_types(db, user_id)}

    summaries = []

    for code in nutrition_guide.available_conditions():
        guide = nutrition_guide.get_guide(code)

        if guide is None:  # pragma: no cover - available_conditions 가 보증한다
            continue

        summaries.append(
            {
                "condition": guide.condition,
                "label": guide.label,
                "intro": guide.intro,
                "axis_count": len(guide.axes),
                "is_mine": guide.condition in mine,
            }
        )

    # 내 질환을 앞에 둔다. 홈 카드는 앞에서부터 그리므로 순서가 곧 노출 우선순위다.
    # 안정 정렬이라 전부 false 면 기본 순서가 그대로 유지된다.
    summaries.sort(key=lambda item: not item["is_mine"])

    return summaries
