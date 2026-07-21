"""그룹 운동 챌린지 (docs/ACTIVITY_GUIDANCE.md 3-4).

⚠️ **순위는 제3자 노출이다.** 내 활동량을 같은 그룹의 다른 사람에게 보이는 것이라, 우리가 건강정보를
수집·이용하는 데 대한 `sensitive_health` 동의로는 커버되지 않는다. 그래서 `group_activity_share`
동의를 따로 받고, **동의한 멤버만 순위에 나타난다**. 참여자 테이블을 두지 않는 이유가 이것이다 —
동의가 곧 참여 의사다.

노출 범위도 최소로 둔다: 닉네임(이미 그룹에서 보인다)과 **합계 분·달성 여부**만 준다.
개별 운동 기록·종류·메모·칼로리는 남에게 보이지 않는다.
"""

from datetime import date, datetime

from timeutil import UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.auth_model import User
from models.consent_model import UserConsent
from models.group_model import GroupChallenge, GroupMember
from models.health_model import ExerciseLog
from services import consent_service, exercise_service, group_service

MAX_TITLE_LENGTH = 60


def _ensure_member(db: Session, user_id: int, group_id: int) -> GroupMember:
    """그룹 멤버가 아니면 **존재를 숨긴다** — 그룹 라우트의 404 은닉 규칙과 같다."""
    membership = group_service.get_membership(db, group_id, user_id)
    if membership is None:
        raise LookupError("그룹을 찾을 수 없습니다.")
    return membership


def _sharing_user_ids(db: Session, user_ids: list[int]) -> set[int]:
    """활동 공유에 동의(하고 철회하지 않은) 사용자만 추린다."""
    if not user_ids:
        return set()

    rows = db.scalars(
        select(UserConsent.user_id).where(
            UserConsent.user_id.in_(user_ids),
            UserConsent.kind == consent_service.GROUP_ACTIVITY_SHARE,
            UserConsent.revoked_at.is_(None),
        )
    ).all()
    return set(rows)


def create_challenge(
    db: Session,
    user_id: int,
    group_id: int,
    title: str,
    target_minutes: int,
    start_date: date,
    end_date: date,
) -> GroupChallenge:
    _ensure_member(db, user_id, group_id)

    if end_date < start_date:
        raise ValueError("종료일이 시작일보다 빠릅니다.")

    clean_title = title.strip()
    if not clean_title:
        raise ValueError("챌린지 이름을 입력해주세요.")

    challenge = GroupChallenge(
        group_id=group_id,
        created_by=user_id,
        title=clean_title[:MAX_TITLE_LENGTH],
        target_minutes=target_minutes,
        start_date=start_date,
        end_date=end_date,
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)
    return challenge


def list_challenges(db: Session, user_id: int, group_id: int) -> list[GroupChallenge]:
    _ensure_member(db, user_id, group_id)

    return list(
        db.scalars(
            select(GroupChallenge)
            .where(
                GroupChallenge.group_id == group_id,
                GroupChallenge.deleted_at.is_(None),
            )
            .order_by(GroupChallenge.start_date.desc(), GroupChallenge.id.desc())
        ).all()
    )


def _get_challenge(db: Session, user_id: int, group_id: int, challenge_id: int) -> GroupChallenge:
    _ensure_member(db, user_id, group_id)

    challenge = db.scalar(
        select(GroupChallenge).where(
            GroupChallenge.id == challenge_id,
            GroupChallenge.group_id == group_id,
            GroupChallenge.deleted_at.is_(None),
        )
    )
    if challenge is None:
        raise LookupError("챌린지를 찾을 수 없습니다.")
    return challenge


def delete_challenge(db: Session, user_id: int, group_id: int, challenge_id: int) -> None:
    """만든 사람 또는 그룹 소유자만 지울 수 있다."""
    challenge = _get_challenge(db, user_id, group_id, challenge_id)
    membership = _ensure_member(db, user_id, group_id)

    if challenge.created_by != user_id and membership.role != "owner":
        raise PermissionError("챌린지를 삭제할 권한이 없습니다.")

    challenge.deleted_at = datetime.now(UTC)
    db.commit()


def get_challenge_detail(db: Session, user_id: int, group_id: int, challenge_id: int) -> dict:
    """챌린지 + 순위. **활동 공유에 동의한 멤버만** 순위에 담긴다."""
    challenge = _get_challenge(db, user_id, group_id, challenge_id)

    # 닉네임은 조인으로 가져온다 (GroupMember 에 user 관계가 없다 — group_service 와 같은 방식).
    members = db.execute(
        select(GroupMember, User.nickname)
        .join(User, User.id == GroupMember.user_id)
        .where(GroupMember.group_id == group_id)
        .order_by(GroupMember.joined_at.asc(), GroupMember.id.asc())
    ).all()
    member_ids = [member.user_id for member, _ in members]
    sharing = _sharing_user_ids(db, member_ids)

    start = datetime.combine(challenge.start_date, datetime.min.time(), tzinfo=UTC)
    end = datetime.combine(challenge.end_date, datetime.max.time(), tzinfo=UTC)

    rows = list(
        db.scalars(
            select(ExerciseLog).where(
                ExerciseLog.user_id.in_(sharing or [-1]),
                ExerciseLog.deleted_at.is_(None),
                ExerciseLog.performed_at >= start,
                ExerciseLog.performed_at <= end,
            )
        ).all()
    )

    minutes_by_user: dict[int, int] = {}
    for row in rows:
        minutes_by_user[row.user_id] = minutes_by_user.get(row.user_id, 0) + (
            exercise_service.equivalent_minutes(row)
        )

    entries = []
    for member, nickname in members:
        if member.user_id not in sharing:
            # 동의하지 않은 멤버는 순위에 **넣지 않는다**. 이름조차 활동 맥락에 올리지 않는다.
            continue

        minutes = minutes_by_user.get(member.user_id, 0)
        entries.append(
            {
                "user_id": member.user_id,
                "nickname": group_service.display_name(nickname),
                "minutes": minutes,
                "achieved": minutes >= challenge.target_minutes,
                "is_me": member.user_id == user_id,
            }
        )

    # 많이 한 순. 동점이면 닉네임 순으로 안정 정렬한다.
    entries.sort(key=lambda entry: (-entry["minutes"], entry["nickname"]))
    for index, entry in enumerate(entries, start=1):
        entry["rank"] = index

    today = datetime.now(UTC).date()

    return {
        "id": challenge.id,
        "group_id": challenge.group_id,
        "title": challenge.title,
        "target_minutes": challenge.target_minutes,
        "start_date": challenge.start_date,
        "end_date": challenge.end_date,
        "is_active": challenge.start_date <= today <= challenge.end_date,
        "participant_count": len(entries),
        "member_count": len(members),
        # 내가 공유에 동의했는지. false 면 앱이 "동의하면 순위에 참여할 수 있어요"를 띄운다.
        "i_am_sharing": user_id in sharing,
        "entries": entries,
    }


def to_summary(challenge: GroupChallenge) -> dict:
    today = datetime.now(UTC).date()

    return {
        "id": challenge.id,
        "group_id": challenge.group_id,
        "title": challenge.title,
        "target_minutes": challenge.target_minutes,
        "start_date": challenge.start_date,
        "end_date": challenge.end_date,
        "is_active": challenge.start_date <= today <= challenge.end_date,
    }
