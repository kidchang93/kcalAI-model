"""하루 끼니 목록의 순서가 결정적인지 (`list_meals`).

같은 날 기록은 `logged_at` 이 **같은 값으로 몰린다** — 앱이 과거 날짜를 UTC 정오로 앵커하기
때문이다(DATA_MODEL 4장). 그래서 시각 하나만으로 정렬하면 순서를 DB 물리 순서가 결정하고,
항목을 더해 UPDATE 된 끼니가 목록 맨 뒤로 밀린다. 사용자에겐 "방금 추가한 기록이 안 보인다"로
읽히므로, 여기서 고정하려는 것은 성능이 아니라 **화면에 보이는 순서**다.
"""

from datetime import datetime, timedelta

import pytest
from timeutil import UTC

from models.auth_model import User
from services import health_service

TODAY = datetime.now(UTC).date()
NOON = datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC) + timedelta(hours=12)


@pytest.fixture
def user(db):
    row = User(kakao_id="meal-ordering-test", nickname="정렬테스터")
    db.add(row)
    db.flush()
    return row


def _item(label: str, kcal: int) -> dict:
    return {
        "food_label": label,
        "serving_ratio": 1.0,
        "kcal": kcal,
        "source": "manual",
        "confidence": None,
    }


def _create(db, user, meal_type: str, kcal: int, logged_at: datetime):
    return health_service.create_meal(
        db,
        user_id=user.id,
        meal_type=meal_type,
        logged_at=logged_at,
        photo_s3_key=None,
        items=[_item(f"{meal_type}-음식", kcal)],
    )


def test_same_timestamp_keeps_creation_order(db, user):
    """시각이 모두 같아도 만든 순서(id)로 나온다."""
    created = [
        _create(db, user, "breakfast", 100, NOON),
        _create(db, user, "lunch", 200, NOON),
        _create(db, user, "dinner", 300, NOON),
    ]

    listed = health_service.list_meals(db, user.id, TODAY)

    assert [meal.id for meal in listed] == [meal.id for meal in created]


def test_updated_meal_keeps_its_place(db, user):
    """항목을 더한 끼니가 목록 맨 뒤로 밀리지 않는다 (이 버그의 재현 경로)."""
    breakfast = _create(db, user, "breakfast", 100, NOON)
    lunch = _create(db, user, "lunch", 200, NOON)
    _create(db, user, "dinner", 300, NOON)

    # 앱의 '항목 추가'(append)와 같은 호출 — logged_at 생략은 기존 시각 유지다.
    health_service.update_meal(
        db,
        user_id=user.id,
        meal_id=lunch.id,
        meal_type="lunch",
        logged_at=None,
        photo_s3_key=None,
        items=[_item("lunch-음식", 200), _item("추가한 음식", 160)],
    )

    listed = health_service.list_meals(db, user.id, TODAY)

    assert [meal.id for meal in listed][:2] == [breakfast.id, lunch.id]
    assert listed[1].total_kcal == 360


def test_earlier_time_still_wins(db, user):
    """시각이 다르면 시각이 먼저다 — id 는 어디까지나 동점 처리용이다."""
    late = _create(db, user, "dinner", 300, NOON + timedelta(hours=6))
    early = _create(db, user, "breakfast", 100, NOON - timedelta(hours=6))

    listed = health_service.list_meals(db, user.id, TODAY)

    assert [meal.id for meal in listed] == [early.id, late.id]
