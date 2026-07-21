from datetime import date

from pydantic import BaseModel, Field

# 그룹 운동 챌린지 계약 (docs/ACTIVITY_GUIDANCE.md 3-4).
#
# ⚠️ 순위는 **제3자 노출**이라 `group_activity_share` 동의를 한 멤버만 담긴다.
# 노출은 최소로 — 닉네임·합계 분·달성 여부까지다. 개별 기록·종류·칼로리는 남에게 보이지 않는다.


class ChallengeCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=60)
    # 1인당 목표(중강도 환산 분). 고강도는 2배로 환산해 비교한다.
    target_minutes: int = Field(..., ge=1, le=10000)
    start_date: date
    end_date: date


class ChallengeSummary(BaseModel):
    id: int
    group_id: int
    title: str
    target_minutes: int
    start_date: date
    end_date: date
    is_active: bool


class ChallengeListResponse(BaseModel):
    challenges: list[ChallengeSummary]


class ChallengeEntry(BaseModel):
    user_id: int
    nickname: str
    # 기간 내 중강도 환산 합계.
    minutes: int
    achieved: bool
    rank: int
    is_me: bool


class ChallengeDetailResponse(ChallengeSummary):
    # 순위에 실제로 담긴 사람 수(공유 동의자)와 그룹 전체 멤버 수. 둘이 다르면 앱이 그 차이를 설명한다.
    participant_count: int
    member_count: int
    # 내가 공유에 동의했는지. false 면 앱이 동의 안내를 띄운다(챌린지 자체는 볼 수 있다).
    i_am_sharing: bool
    entries: list[ChallengeEntry]


class ChallengeError(BaseModel):
    detail: str
