"""그룹 챌린지 — 특히 **동의 게이트**를 검증한다 (docs/ACTIVITY_GUIDANCE.md 3-4).

순위는 제3자에게 내 건강 데이터를 보이는 것이라, group_activity_share 동의가 없으면 순위에
나타나지 않아야 한다. 이 규칙이 깨지면 동의 없는 개인정보 제3자 제공이 된다.
"""

from datetime import date, datetime, timedelta

import pytest
from timeutil import UTC

from models.auth_model import User
from services import challenge_service, consent_service, exercise_service, group_service

TODAY = datetime.now(UTC).date()
PERIOD_START = TODAY - timedelta(days=3)
PERIOD_END = TODAY + timedelta(days=3)


def _user(db, suffix: str) -> User:
    row = User(kakao_id=f"challenge-{suffix}", nickname=f"챌린지{suffix}")
    db.add(row)
    db.flush()
    return row


def _share(db, user: User) -> None:
    consent_service.create_consent(
        db,
        user.id,
        consent_service.GROUP_ACTIVITY_SHARE,
        consent_service.GROUP_ACTIVITY_SHARE_VERSION,
    )
    db.flush()


def _log(db, user: User, minutes: int, intensity: str = "moderate") -> None:
    exercise_service.create_exercise(
        db,
        user.id,
        "walking" if intensity != "vigorous" else "running",
        minutes,
        intensity,
        None,
        datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC) + timedelta(hours=12),
        None,
    )


@pytest.fixture
def group_with_two(db):
    owner = _user(db, "owner")
    member = _user(db, "member")
    group = group_service.create_group(db, owner.id, "가족", "family")
    group_id = group["id"]
    group_service.join_group(db, member.id, group["invite_code"])
    db.flush()
    return owner, member, group_id


@pytest.fixture
def challenge(db, group_with_two):
    owner, _member, group_id = group_with_two
    return challenge_service.create_challenge(
        db, owner.id, group_id, "이번 주 같이 걷기", 100, PERIOD_START, PERIOD_END
    )


class TestConsentGate:
    def test_member_without_consent_is_absent_from_leaderboard(self, db, group_with_two, challenge):
        owner, member, group_id = group_with_two
        _share(db, owner)
        # member 는 동의하지 않았다.
        _log(db, owner, 60)
        _log(db, member, 200)

        detail = challenge_service.get_challenge_detail(db, owner.id, group_id, challenge.id)
        user_ids = {entry["user_id"] for entry in detail["entries"]}

        # 더 많이 운동했더라도 **동의 없이는 순위에 나오지 않는다** — 이름조차 올리지 않는다.
        assert member.id not in user_ids
        assert owner.id in user_ids
        assert detail["participant_count"] == 1
        assert detail["member_count"] == 2

    def test_revoked_consent_removes_from_leaderboard(self, db, group_with_two, challenge):
        owner, member, group_id = group_with_two
        _share(db, owner)
        _share(db, member)
        _log(db, member, 60)

        before = challenge_service.get_challenge_detail(db, owner.id, group_id, challenge.id)
        assert member.id in {entry["user_id"] for entry in before["entries"]}

        consent_service.revoke_consent(db, member.id, consent_service.GROUP_ACTIVITY_SHARE)
        db.flush()

        after = challenge_service.get_challenge_detail(db, owner.id, group_id, challenge.id)
        assert member.id not in {entry["user_id"] for entry in after["entries"]}

    def test_i_am_sharing_flag(self, db, group_with_two, challenge):
        owner, _member, group_id = group_with_two

        detail = challenge_service.get_challenge_detail(db, owner.id, group_id, challenge.id)
        assert detail["i_am_sharing"] is False

        _share(db, owner)
        detail = challenge_service.get_challenge_detail(db, owner.id, group_id, challenge.id)
        assert detail["i_am_sharing"] is True

    def test_leaderboard_exposes_only_totals(self, db, group_with_two, challenge):
        owner, _member, group_id = group_with_two
        _share(db, owner)
        _log(db, owner, 30)

        entry = challenge_service.get_challenge_detail(db, owner.id, group_id, challenge.id)[
            "entries"
        ][0]
        # 개별 기록·종류·메모·칼로리는 남에게 보이지 않는다.
        assert set(entry.keys()) == {"user_id", "nickname", "minutes", "achieved", "rank", "is_me"}


class TestMembershipAndRanking:
    def test_non_member_cannot_see_group_challenges(self, db, group_with_two, challenge):
        _owner, _member, group_id = group_with_two
        outsider = _user(db, "outsider")

        # 비멤버에게는 그룹의 존재 자체를 숨긴다 (404).
        with pytest.raises(LookupError):
            challenge_service.list_challenges(db, outsider.id, group_id)
        with pytest.raises(LookupError):
            challenge_service.get_challenge_detail(db, outsider.id, group_id, challenge.id)

    def test_vigorous_counts_double_in_ranking(self, db, group_with_two, challenge):
        owner, member, group_id = group_with_two
        _share(db, owner)
        _share(db, member)
        _log(db, owner, 60, "moderate")
        _log(db, member, 40, "vigorous")  # 환산 80분 → 1위

        entries = challenge_service.get_challenge_detail(db, owner.id, group_id, challenge.id)[
            "entries"
        ]
        assert entries[0]["user_id"] == member.id
        assert entries[0]["minutes"] == 80
        assert entries[0]["rank"] == 1
        assert entries[1]["minutes"] == 60

    def test_achieved_uses_challenge_target(self, db, group_with_two, challenge):
        owner, _member, group_id = group_with_two
        _share(db, owner)
        _log(db, owner, 100)  # 목표 100분 정확히 달성

        entry = challenge_service.get_challenge_detail(db, owner.id, group_id, challenge.id)[
            "entries"
        ][0]
        assert entry["achieved"] is True

    def test_records_outside_period_are_excluded(self, db, group_with_two, challenge):
        owner, _member, group_id = group_with_two
        _share(db, owner)
        exercise_service.create_exercise(
            db,
            owner.id,
            "walking",
            120,
            "moderate",
            None,
            datetime.combine(PERIOD_START - timedelta(days=5), datetime.min.time(), tzinfo=UTC),
            None,
        )

        entry = challenge_service.get_challenge_detail(db, owner.id, group_id, challenge.id)[
            "entries"
        ][0]
        assert entry["minutes"] == 0


class TestLifecycle:
    def test_reversed_period_rejected(self, db, group_with_two):
        owner, _member, group_id = group_with_two
        with pytest.raises(ValueError):
            challenge_service.create_challenge(
                db, owner.id, group_id, "잘못된 기간", 100, PERIOD_END, PERIOD_START
            )

    def test_only_creator_or_owner_can_delete(self, db, group_with_two, challenge):
        owner, member, group_id = group_with_two

        # 만든 사람(owner)도 그룹 소유자(owner)도 아닌 멤버는 지울 수 없다.
        with pytest.raises(PermissionError):
            challenge_service.delete_challenge(db, member.id, group_id, challenge.id)

        # 멤버가 만든 챌린지는 그룹 소유자가 지울 수 있다.
        made_by_member = challenge_service.create_challenge(
            db, member.id, group_id, "멤버 챌린지", 100, PERIOD_START, PERIOD_END
        )
        challenge_service.delete_challenge(db, owner.id, group_id, made_by_member.id)

        remaining = {row.id for row in challenge_service.list_challenges(db, owner.id, group_id)}
        assert made_by_member.id not in remaining
        # 만든 사람 본인도 지울 수 있다.
        challenge_service.delete_challenge(db, owner.id, group_id, challenge.id)

    def test_deleted_challenge_is_hidden(self, db, group_with_two, challenge):
        owner, _member, group_id = group_with_two
        challenge_service.delete_challenge(db, owner.id, group_id, challenge.id)

        assert challenge_service.list_challenges(db, owner.id, group_id) == []
        with pytest.raises(LookupError):
            challenge_service.get_challenge_detail(db, owner.id, group_id, challenge.id)

    def test_is_active_reflects_period(self, db, group_with_two):
        owner, _member, group_id = group_with_two
        past = challenge_service.create_challenge(
            db,
            owner.id,
            group_id,
            "지난 챌린지",
            100,
            TODAY - timedelta(days=20),
            TODAY - timedelta(days=10),
        )

        assert challenge_service.to_summary(past)["is_active"] is False
        assert isinstance(past.start_date, date)
