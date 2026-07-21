"""운동 기록 서비스 검증 (docs/ACTIVITY_GUIDANCE.md 3-2).

끼니 기록과 같은 규약(UTC 자정 경계·soft delete·404 존재 은닉)을 지키는지, 그리고 주간 집계가
지침 환산(고강도 1분 = 중강도 2분)을 제대로 하는지 본다.
"""

from datetime import datetime, timedelta

import pytest
from timeutil import UTC

from models.auth_model import User
from models.health_model import UserProfile
from services import exercise_service, fitness_rules

DAY = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


@pytest.fixture
def user(db):
    row = User(kakao_id="exercise-test", nickname="운동테스터")
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def user_with_profile(db, user):
    db.add(
        UserProfile(
            user_id=user.id,
            sex="male",
            birth_year=1993,
            height_cm=175,
            weight_kg=70,
            activity_level="moderate",
        )
    )
    db.flush()
    return user


class TestCreate:
    def test_kcal_is_estimated_from_met_and_weight(self, db, user_with_profile):
        row = exercise_service.create_exercise(
            db, user_with_profile.id, "running", 30, None, None, DAY, None
        )
        # 달리기 MET 8.3 × 70kg × 0.5h = 290.5 → 290
        assert row.kcal == 290
        # 종류별 기본 강도가 채워진다 (달리기 = 고강도).
        assert row.intensity == "vigorous"
        assert row.source == "manual"

    def test_kcal_is_null_without_profile(self, db, user):
        # 체중을 모르면 지어내지 않는다 — null 로 두고 앱이 직접 입력을 받는다.
        row = exercise_service.create_exercise(db, user.id, "running", 30, None, None, DAY, None)
        assert row.kcal is None

    def test_user_kcal_wins(self, db, user_with_profile):
        row = exercise_service.create_exercise(
            db, user_with_profile.id, "running", 30, None, 500, DAY, None
        )
        assert row.kcal == 500

    def test_unknown_type_rejected(self, db, user):
        with pytest.raises(ValueError):
            exercise_service.create_exercise(db, user.id, "teleportation", 30, None, None, DAY, None)


class TestListAndOwnership:
    def test_list_is_scoped_to_utc_day(self, db, user):
        exercise_service.create_exercise(db, user.id, "walking", 30, None, None, DAY, None)
        # 다음 날 00:30 UTC — 같은 달력일이 아니므로 조회에 안 잡혀야 한다.
        next_day = DAY.replace(hour=0, minute=30) + timedelta(days=1)
        exercise_service.create_exercise(db, user.id, "walking", 30, None, None, next_day, None)

        rows = exercise_service.list_exercises(db, user.id, DAY.date())
        assert len(rows) == 1

    def test_soft_delete_hides_from_list(self, db, user):
        row = exercise_service.create_exercise(db, user.id, "walking", 30, None, None, DAY, None)
        exercise_service.delete_exercise(db, user.id, row.id)

        assert exercise_service.list_exercises(db, user.id, DAY.date()) == []
        # 행 자체는 남아 있다 (soft delete).
        assert row.deleted_at is not None

    def test_other_users_record_is_404(self, db, user):
        other = User(kakao_id="exercise-other", nickname="남")
        db.add(other)
        db.flush()
        row = exercise_service.create_exercise(db, other.id, "walking", 30, None, None, DAY, None)

        # 남의 기록은 '없음'과 구분되지 않아야 한다.
        with pytest.raises(LookupError):
            exercise_service.update_exercise(
                db, user.id, row.id, "walking", 10, None, None, None, None
            )
        with pytest.raises(LookupError):
            exercise_service.delete_exercise(db, user.id, row.id)

    def test_update_keeps_performed_at_when_omitted(self, db, user):
        row = exercise_service.create_exercise(db, user.id, "walking", 30, None, None, DAY, None)
        updated = exercise_service.update_exercise(
            db, user.id, row.id, "cycling", 45, None, None, None, "메모"
        )
        assert updated.performed_at == DAY
        assert updated.exercise_type == "cycling"
        assert updated.duration_minutes == 45


class TestSummary:
    def test_vigorous_counts_double(self, db, user):
        # 중강도 50분 + 고강도 50분 → 환산 50 + 100 = 150분 (권장 하한 달성).
        exercise_service.create_exercise(db, user.id, "walking", 50, "moderate", None, DAY, None)
        exercise_service.create_exercise(db, user.id, "running", 50, "vigorous", None, DAY, None)

        summary = exercise_service.get_summary(db, user.id, DAY.date(), DAY.date())
        assert summary["moderate_minutes"] == 50
        assert summary["vigorous_minutes"] == 50
        assert summary["equivalent_moderate_minutes"] == 150
        assert summary["achieved"] is True
        assert summary["remaining_minutes"] == 0

    def test_remaining_minutes(self, db, user):
        exercise_service.create_exercise(db, user.id, "walking", 30, "moderate", None, DAY, None)
        summary = exercise_service.get_summary(db, user.id, DAY.date(), DAY.date())
        assert summary["remaining_minutes"] == fitness_rules.AEROBIC_MODERATE_MIN_MINUTES - 30
        assert summary["achieved"] is False

    def test_light_does_not_count_toward_goal(self, db, user):
        # 저강도는 권장량 집계에 들어가지 않는다 (지침 기준). 기록은 보여준다.
        exercise_service.create_exercise(db, user.id, "yoga", 200, "light", None, DAY, None)
        summary = exercise_service.get_summary(db, user.id, DAY.date(), DAY.date())
        assert summary["light_minutes"] == 200
        assert summary["equivalent_moderate_minutes"] == 0
        assert summary["achieved"] is False

    def test_strength_counted_in_days_not_minutes(self, db, user):
        # 같은 날 두 번 해도 1일이다 — 지침이 '주 2일 이상'으로 권고하기 때문.
        exercise_service.create_exercise(db, user.id, "strength", 30, None, None, DAY, None)
        exercise_service.create_exercise(db, user.id, "strength", 30, None, None, DAY, None)
        exercise_service.create_exercise(
            db, user.id, "strength", 30, None, None, DAY + timedelta(days=1), None
        )

        summary = exercise_service.get_summary(
            db, user.id, DAY.date(), (DAY + timedelta(days=1)).date()
        )
        assert summary["strength_days"] == 2

    def test_deleted_records_are_excluded(self, db, user):
        row = exercise_service.create_exercise(
            db, user.id, "running", 60, "vigorous", None, DAY, None
        )
        exercise_service.delete_exercise(db, user.id, row.id)

        summary = exercise_service.get_summary(db, user.id, DAY.date(), DAY.date())
        assert summary["exercise_count"] == 0
        assert summary["equivalent_moderate_minutes"] == 0

    def test_reversed_range_rejected(self, db, user):
        with pytest.raises(ValueError):
            exercise_service.get_summary(
                db, user.id, DAY.date(), (DAY - timedelta(days=1)).date()
            )


class TestGoalAndStreak:
    """개인 주간 목표와 스트릭 (docs/ACTIVITY_GUIDANCE.md 3-4)."""

    def test_default_goal_is_the_guideline(self, db, user):
        # 목표를 정하지 않아도 기능이 동작해야 한다 — 지침 권장량이 기본값이다.
        goal = exercise_service.resolve_goal(db, user.id)
        assert goal["weekly_minutes"] == fitness_rules.AEROBIC_MODERATE_MIN_MINUTES
        assert goal["weekly_strength_days"] == fitness_rules.STRENGTH_DAYS_MIN
        assert goal["is_default"] is True

    def test_upsert_closes_previous_goal(self, db, user):
        exercise_service.upsert_goal(db, user.id, 200, 3)
        exercise_service.upsert_goal(db, user.id, 90, 1)

        goal = exercise_service.resolve_goal(db, user.id)
        assert goal["weekly_minutes"] == 90
        assert goal["is_default"] is False
        # 이전 목표는 닫혀서 이력으로 남는다 (열린 목표는 언제나 하나).
        assert exercise_service.get_open_goal(db, user.id).weekly_minutes == 90

    def test_summary_uses_user_goal_not_guideline(self, db, user):
        exercise_service.upsert_goal(db, user.id, 60, 2)
        exercise_service.create_exercise(db, user.id, "walking", 60, "moderate", None, DAY, None)

        summary = exercise_service.get_summary(db, user.id, DAY.date(), DAY.date())
        # 지침(150분) 기준이면 미달성이지만, 사용자 목표(60분) 기준으로는 달성이다.
        assert summary["target_minutes"] == 60
        assert summary["achieved"] is True
        assert summary["remaining_minutes"] == 0
        # 지침 값도 함께 준다 — 목표를 낮게 잡았어도 지침이 뭔지 볼 수 있어야 한다.
        assert summary["recommended_min_minutes"] == fitness_rules.AEROBIC_MODERATE_MIN_MINUTES

    def test_streak_counts_consecutive_weeks(self, db, user):
        from datetime import date as date_cls

        exercise_service.upsert_goal(db, user.id, 60, 2)
        today = datetime.now(UTC).date()
        this_week_start, _ = exercise_service.week_bounds(today)

        # 지난 2주를 각각 달성시킨다 (이번 주는 비워 둔다).
        for weeks_ago in (1, 2):
            day = this_week_start - timedelta(weeks=weeks_ago)
            exercise_service.create_exercise(
                db,
                user.id,
                "walking",
                60,
                "moderate",
                None,
                datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=12),
                None,
            )

        assert isinstance(this_week_start, date_cls)
        # 진행 중인 주(이번 주)는 미달성이어도 스트릭을 끊지 않는다 — 아직 기회가 있다.
        assert exercise_service.calculate_streak(db, user.id, today, 60) == 2

    def test_streak_breaks_on_missed_week(self, db, user):
        today = datetime.now(UTC).date()
        this_week_start, _ = exercise_service.week_bounds(today)

        # 3주 전만 달성 — 1·2주 전이 비어 스트릭이 끊긴다.
        day = this_week_start - timedelta(weeks=3)
        exercise_service.create_exercise(
            db,
            user.id,
            "walking",
            60,
            "moderate",
            None,
            datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=12),
            None,
        )

        assert exercise_service.calculate_streak(db, user.id, today, 60) == 0

    def test_light_intensity_does_not_build_streak(self, db, user):
        today = datetime.now(UTC).date()
        this_week_start, _ = exercise_service.week_bounds(today)
        day = this_week_start - timedelta(weeks=1)

        exercise_service.create_exercise(
            db,
            user.id,
            "yoga",
            300,
            "light",
            None,
            datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=12),
            None,
        )

        # 저강도는 권장량 집계에 들어가지 않으므로 스트릭도 쌓이지 않는다.
        assert exercise_service.calculate_streak(db, user.id, today, 60) == 0
