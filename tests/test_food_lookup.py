"""음식 이름 → DB 행 조회(`nutrition_service._find_in_dataset`) 회귀.

2026-10-17: 사진 인식이 "소고기쌀국수"를 정확히 냈는데 조회가 생고기 "소고기"(나트륨 51 mg)를 골랐다
(쌀국수는 1,650 mg). trgm 이 문자열 앞에 가중을 줘서 앞쪽 재료가 이긴 것이다 — 한국어 음식 이름은
뒤가 요리다. 공유 개발 DB 의 실제 행과 겹치지 않도록 지어낸 이름을 쓴다.
"""

from models.health_model import FoodNutrition
from services.nutrition_service import _find_in_dataset


def _add(db, label: str) -> None:
    db.add(FoodNutrition(food_label=label, kcal_per_serving=100, serving_desc="1인분", source="mfds"))
    db.flush()


def test_dish_at_the_end_beats_ingredient_at_the_front(db):
    _add(db, "쿼쿼고기")  # 앞쪽 재료 — trgm 은 이쪽을 더 닮았다고 본다
    _add(db, "퀴퀴국수")  # 뒤쪽 요리

    assert _find_in_dataset(db, "쿼쿼고기퀴퀴국수").food_label == "퀴퀴국수"
