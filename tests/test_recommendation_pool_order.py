"""추천 후보 풀의 그룹 내 정렬 — 대표 메뉴가 먼저, 그 안에서 질환 태그 (2026-10-05, DATA_MODEL 12·13장).

실제 식약처 행과 섞이지 않게 **테스트 전용 그룹**만 보도록 끼니 매핑을 바꿔 끼운다. 이름에 '_'를
반드시 넣는 이유: LIKE 로 판정하면 '_'가 와일드카드라 모든 행이 변형으로 잡히는데, 그러면 이
테스트가 나트륨 순서만 남아 깨진다(실제로 한 번 그 실수를 했다).
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from models.health_model import FoodNutrition
from services import recommendation_service as svc

GROUP = "테스트그룹-대표메뉴정렬"


@pytest.fixture
def pool_rows(db, monkeypatch):
    monkeypatch.setitem(svc.MEAL_FOOD_GROUPS, "lunch", (GROUP,))

    # 변형 행일수록 나트륨을 낮게 둔다 — 태그 정렬이 첫 키였다면 변형이 앞에 온다.
    for label, sodium in (
        ("테스트변형_저염", "5"),
        ("테스트대표 고염", "900"),
        ("테스트상품(R)", "1"),
        ("테스트대표 저염", "100"),
    ):
        db.add(
            FoodNutrition(
                food_label=label,
                kcal_per_serving=300,
                serving_desc="1인분",
                sodium_mg=Decimal(sodium),
                food_group=GROUP,
                source="mfds",
            )
        )
    db.flush()


def _pool_labels(db, conditions) -> list[str]:
    return [row.food_label for row in svc._candidate_pool(db, "lunch", None, conditions, [])]


def test_representative_menus_come_first_and_tag_sort_applies_within(db, pool_rows):
    low_sodium = SimpleNamespace(dietary_tags=["low_sodium"])

    assert _pool_labels(db, [low_sodium]) == [
        "테스트대표 저염",
        "테스트대표 고염",
        "테스트상품(R)",
        "테스트변형_저염",
    ]


def test_without_tags_representative_menus_still_lead(db, pool_rows):
    assert _pool_labels(db, [])[:2] == ["테스트대표 고염", "테스트대표 저염"]  # 그 안은 id 순
