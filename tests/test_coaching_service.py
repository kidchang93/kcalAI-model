"""주간 조언 — 규칙이 근거대로 발동하는지 (docs/ACTIVITY_GUIDANCE.md 3-5).

조언은 규칙 기반이라 **같은 상황이면 같은 답**이 나와야 한다. 그 재현성과, 질병이 있을 때
강도·종목을 제시하지 않는다는 책임 경계를 고정한다.
"""

from datetime import datetime, timedelta

import pytest
from timeutil import UTC

from models.auth_model import User
from models.consent_model import UserCondition
from models.health_model import UserProfile
from services import coaching_service, exercise_service, health_service

TODAY = datetime.now(UTC).date()


@pytest.fixture
def user(db):
    row = User(kakao_id="coaching-test", nickname="조언테스터")
    db.add(row)
    db.flush()
    db.add(
        UserProfile(
            user_id=row.id,
            sex="male",
            birth_year=1993,
            height_cm=175,
            weight_kg=70,
            activity_level="moderate",
        )
    )
    db.flush()
    return row


def _log_exercise(db, user, minutes: int, intensity: str = "moderate", kind: str = "walking"):
    exercise_service.create_exercise(
        db,
        user.id,
        kind,
        minutes,
        intensity,
        None,
        datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC) + timedelta(hours=12),
        None,
    )


def _codes(result: dict) -> set[str]:
    return {item["code"] for item in result["items"]}


class TestActivityAdvice:
    def test_no_exercise_this_week(self, db, user):
        result = coaching_service.get_weekly_coaching(db, user.id, TODAY)
        assert "activity_none" in _codes(result)

    def test_short_of_goal_gives_daily_breakdown(self, db, user):
        _log_exercise(db, user, 80)
        result = coaching_service.get_weekly_coaching(db, user.id, TODAY)

        item = next(entry for entry in result["items"] if entry["code"] == "activity_short")
        # 남은 총량이 아니라 '하루 몇 분'으로 환산해 준다 — 실행 가능한 단위여야 한다.
        assert "하루" in item["message"]
        assert item["evidence"] is not None

    def test_achieved_is_praised(self, db, user):
        _log_exercise(db, user, 160)
        result = coaching_service.get_weekly_coaching(db, user.id, TODAY)

        assert "activity_achieved" in _codes(result)
        item = next(entry for entry in result["items"] if entry["code"] == "activity_achieved")
        assert item["tone"] == "good"

    def test_strength_shortfall(self, db, user):
        _log_exercise(db, user, 160)
        result = coaching_service.get_weekly_coaching(db, user.id, TODAY)
        assert "strength_short" in _codes(result)

    def test_every_item_carries_evidence(self, db, user):
        _log_exercise(db, user, 40)
        result = coaching_service.get_weekly_coaching(db, user.id, TODAY)
        # 조언만 있고 근거가 없으면 사용자가 판단할 수 없다.
        assert all(item["evidence"] for item in result["items"])


class TestConditionBoundary:
    def test_condition_softens_strength_advice(self, db, user):
        db.add(UserCondition(user_id=user.id, condition="ckd"))
        db.flush()
        _log_exercise(db, user, 160)

        result = coaching_service.get_weekly_coaching(db, user.id, TODAY)
        item = next(entry for entry in result["items"] if entry["code"] == "strength_short")

        # 질병이 있으면 종목을 제시하지 않고 의료진 상담으로 돌린다.
        assert "의료진" in item["message"]
        assert "맨몸" not in item["message"]
        assert result["conditions"] == ["신장 질환"]

    def test_notice_states_not_a_medical_device(self, db, user):
        result = coaching_service.get_weekly_coaching(db, user.id, TODAY)
        assert "의료기기가 아니" in result["notice"]


class TestWeightAdvice:
    def _weigh(self, db, user, kg: float, days_ago: int):
        health_service.create_weight(
            db,
            user.id,
            kg,
            datetime.combine(TODAY - timedelta(days=days_ago), datetime.min.time(), tzinfo=UTC),
        )

    def test_ignores_small_fluctuation(self, db, user):
        self._weigh(db, user, 70.0, 20)
        self._weigh(db, user, 70.4, 1)
        # 0.4kg 은 일상 변동이다 — 추세로 보지 않는다.
        assert not {"weight_changed", "weight_against_goal", "weight_on_track"} & _codes(
            coaching_service.get_weekly_coaching(db, user.id, TODAY)
        )

    def test_gaining_while_goal_is_loss(self, db, user):
        health_service.upsert_goal(db, user.id, "loss", None, None)
        self._weigh(db, user, 70.0, 20)
        self._weigh(db, user, 72.5, 1)

        result = coaching_service.get_weekly_coaching(db, user.id, TODAY)
        item = next(entry for entry in result["items"] if entry["code"] == "weight_against_goal")
        # 목표와 반대 방향이면 재설정을 **제안**한다(단정하거나 강요하지 않는다).
        assert item["tone"] == "caution"
        assert "어때요" in item["message"]

    def test_losing_while_goal_is_loss(self, db, user):
        health_service.upsert_goal(db, user.id, "loss", None, None)
        self._weigh(db, user, 72.0, 20)
        self._weigh(db, user, 70.0, 1)

        assert "weight_on_track" in _codes(coaching_service.get_weekly_coaching(db, user.id, TODAY))


class TestOrderingAndLimit:
    def test_caution_comes_first(self, db, user):
        health_service.upsert_goal(db, user.id, "loss", None, None)
        health_service.create_weight(
            db, user.id, 70.0, datetime.combine(TODAY - timedelta(days=20), datetime.min.time(), tzinfo=UTC)
        )
        health_service.create_weight(
            db, user.id, 73.0, datetime.combine(TODAY - timedelta(days=1), datetime.min.time(), tzinfo=UTC)
        )
        _log_exercise(db, user, 160)

        result = coaching_service.get_weekly_coaching(db, user.id, TODAY)
        # 먼저 볼 것을 위로 올린다.
        assert result["items"][0]["tone"] == "caution"

    def test_limited_count(self, db, user):
        _log_exercise(db, user, 10)
        result = coaching_service.get_weekly_coaching(db, user.id, TODAY)
        assert len(result["items"]) <= coaching_service.MAX_ADVICE
