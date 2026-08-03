"""기록 시점 영양 스냅샷이 **응답까지** 나가는지 (`MealItemResponse`).

2026-08-03에 실사용으로 드러난 사고를 고정한다: 리비전 0025가 `meal_items` 에 나트륨·칼륨·인·
당류 스냅샷 컬럼을 넣었는데 **응답 스키마에 필드를 추가하지 않아 앱이 받을 수 없었다.**
저장은 되고 조회는 안 되는 상태였고, 그래서 과거 기록 화면은 kcal 만 그렸다 — 질환 축이
"기록하는 순간에만 보이는" 원인이었다 (`docs/CARE_LOOP.md` §0-3).

컬럼을 추가하고 응답 필드를 빠뜨리는 것은 **조용히 실패한다** — 에러도 경고도 없고, 화면에서
숫자가 안 보일 뿐이다. 그래서 `_SNAPSHOT_COLUMNS` 를 진실로 삼아 대조한다: 축이 늘면 이
테스트가 먼저 깨진다.
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from timeutil import UTC

from models.auth_model import User
from models.health_model import MealItem, MealLog
from schemas.health_schema import MealItemResponse, MealResponse
from services import health_service

TODAY = datetime.now(UTC).date()
NOON = datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC) + timedelta(hours=12)


@pytest.fixture
def user(db):
    row = User(kakao_id="meal-snapshot-test", nickname="스냅샷테스터")
    db.add(row)
    db.flush()
    return row


def test_response_schema_exposes_every_snapshot_column():
    """스냅샷으로 굳히는 축은 **전부** 응답 스키마에 있어야 한다.

    `_SNAPSHOT_COLUMNS` 에 축을 추가하면서 `MealItemResponse` 를 잊으면 여기서 걸린다.
    """
    snapshot_fields = {name for name, _ in health_service._SNAPSHOT_COLUMNS}

    missing = snapshot_fields - set(MealItemResponse.model_fields)

    assert not missing, (
        f"스냅샷 컬럼이 응답에 없다: {sorted(missing)}. "
        "저장만 되고 앱은 받지 못한다 — docs/CARE_LOOP.md §0-3 의 사고와 같은 모양이다."
    )


def _meal_with_snapshot(db, user, **snapshot) -> MealLog:
    """스냅샷 값을 직접 심은 끼니. `create_meal` 은 food_nutrition 을 조회해 채우므로,
    여기서는 **저장된 값이 응답까지 그대로 흐르는지**만 보려고 직접 만든다."""
    meal = MealLog(
        user_id=user.id,
        meal_type="lunch",
        logged_at=NOON,
        total_kcal=430,
        photo_s3_key=None,
    )
    db.add(meal)
    db.flush()

    db.add(
        MealItem(
            meal_log_id=meal.id,
            food_label="제육볶음",
            serving_ratio=Decimal("1.0"),
            kcal=430,
            source="manual",
            confidence=None,
            **snapshot,
        )
    )
    db.flush()

    return meal


def test_snapshot_values_reach_the_response(db, user):
    """DB 에 있는 수치가 응답 직렬화까지 살아 나온다 — 사고의 직접 재현."""
    _meal_with_snapshot(
        db,
        user,
        sodium_mg=Decimal("1200.0"),
        potassium_mg=Decimal("570.0"),
        phosphorus_mg=Decimal("210.0"),
        sugar_g=Decimal("8.5"),
    )

    listed = health_service.list_meals(db, user.id, TODAY)
    item = MealResponse.model_validate(listed[0]).items[0]

    assert item.sodium_mg == 1200.0
    assert item.potassium_mg == 570.0
    assert item.phosphorus_mg == 210.0
    assert item.sugar_g == 8.5


def test_unmeasured_food_stays_null(db, user):
    """실측이 없는 음식은 **0 이 아니라 null** 로 나간다.

    0 으로 내리면 화면이 "나트륨 0mg 을 먹었다"로 그린다 — 침묵이 안전으로 읽히는
    바로 그 실패다(`docs/PRODUCT_STRATEGY.md` §5-2). 없는 것은 없다고 말해야 한다.
    """
    _meal_with_snapshot(db, user)

    listed = health_service.list_meals(db, user.id, TODAY)
    item = MealResponse.model_validate(listed[0]).items[0]

    assert item.sodium_mg is None
    assert item.potassium_mg is None
    assert item.phosphorus_mg is None
    assert item.sugar_g is None
