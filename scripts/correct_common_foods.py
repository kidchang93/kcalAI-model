"""자주 먹는 음식의 1인분 값 보정 → food_nutrition (source='curated' 로 덮어쓴다).

사용법 (반드시 저장소 루트에서):
    venv/bin/python scripts/correct_common_foods.py

배경 (DATA_MODEL.md 12·14장):
- 식약처(mfds) 원본의 **식품중량(1인분 무게)이 일부 음식에서 비현실적으로 작아**(떡볶이 75g,
  제육볶음 136g 등) 1인분 kcal 이 실제보다 크게 과소평가된다. 원물(mfds_raw)은 "100g당"이라
  사과 한 개(약 180g)를 100g 로 계산한다. → 사용자 체감 "칼로리가 너무 작게 나온다".
- 계산 **모델(1인분 기준)은 그대로 두고**, 자주 먹는 음식의 **1인분 값만 현실적으로 보정**한다.
  앱은 여전히 1인분 × serving_ratio(0.5~2) 로 계산한다.

이 스크립트가 seed_curated_foods.py 와 다른 점:
- **source 제한 없이 덮어쓴다** (seed 는 WHERE source='curated' 가드로 mfds 를 못 건드림).
  여기서 고치는 대상은 대부분 이미 mfds/mfds_raw 로 존재하는 행이다.
- 보정 후 **source='curated'** 로 바꾼다 → 이후 import_mfds_food.py 재적재(WHERE source
  in llm,mfds)에도 **보정이 유지**된다. macros·food_group 은 비운다(값-서빙 불일치 방지,
  curated 규약과 동일). curated 라 추천 후보 풀(source='mfds')에서는 빠진다(estimate 전용).
- 멱등: 재실행하면 같은 목표값으로 다시 upsert 된다.

값은 표준 영양 참고치 기반 1인분 근사값이다. 항목/값을 보강하려면 CORRECTIONS 를 고치고
다시 실행하면 된다.
"""

import sys
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert

# 스크립트를 scripts/ 밖의 로컬 모듈(database, models)과 연결한다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import SessionLocal  # noqa: E402
from models.health_model import FoodNutrition  # noqa: E402

SOURCE_CURATED = "curated"

# (food_label, kcal_per_serving, serving_desc) — 현실적 1인분 기준.
# 밀도(kcal/g)를 검산해 상식적 범위로 맞췄다. 이미 정상인 음식(김치찌개 244·비빔밥 634·
# 쌀밥 300·짜장면 683 등)은 건드리지 않는다.
CORRECTIONS: list[tuple[str, int, str]] = [
    # --- 요리(mfds): 1인분 무게가 비현실적으로 작아 과소평가된 것 ---
    ("제육볶음", 430, "1인분 (약 200g)"),
    ("떡볶이", 360, "1인분 (약 250g)"),
    ("돈가스", 560, "1인분 (약 200g)"),
    ("돈까스", 560, "1인분 (약 200g)"),
    ("된장찌개", 170, "1인분 (약 350g)"),
    ("갈비탕", 260, "1인분 (약 400g)"),
    ("설렁탕", 330, "1인분 (약 500g)"),
    ("육개장", 190, "1인분 (약 400g)"),
    ("미역국", 80, "1인분 (약 300g)"),
    ("콩나물국", 40, "1인분 (약 300g)"),
    ("볶음밥", 600, "1인분 (약 350g)"),
    ("소불고기", 400, "1인분 (약 200g)"),
    ("불고기", 400, "1인분 (약 200g)"),
    ("순대", 300, "1인분 (약 200g)"),
    ("달걀말이", 200, "1인분 (약 120g)"),
    ("계란말이", 200, "1인분 (약 120g)"),
    ("달걀찜", 160, "1인분 (약 200g)"),
    ("계란찜", 160, "1인분 (약 200g)"),
    ("족발", 480, "1인분 (약 200g)"),
    # --- 원물 과일·채소(mfds_raw): "100g당" → 현실적 낱개/1인분 ---
    ("사과", 95, "1개 (약 180g)"),
    ("바나나", 105, "1개 (약 120g)"),
    ("귤", 45, "1개 (약 100g)"),
    ("배", 135, "1개 (약 300g)"),
    ("포도", 90, "1인분 (약 150g)"),
    ("딸기", 50, "1인분 (약 150g)"),
    ("수박", 100, "1조각 (약 300g)"),
    ("참외", 70, "1개 (약 200g)"),
    ("오렌지", 65, "1개 (약 130g)"),
    ("감자", 100, "1개 (약 150g)"),
    ("고구마", 180, "1개 (약 130g)"),
    ("옥수수", 155, "1개 (약 150g)"),
]

# UPDATE 시 함께 비우는 컬럼(값-서빙 불일치 방지, curated 규약과 동일).
_NULLED = (
    "carbs_g",
    "protein_g",
    "fat_g",
    "sugar_g",
    "sodium_mg",
    "potassium_mg",
    "phosphorus_mg",
    "food_group",
)


def correct() -> None:
    rows = [
        {
            "food_label": label,
            "kcal_per_serving": kcal,
            "serving_desc": serving_desc,
            "source": SOURCE_CURATED,
        }
        for label, kcal, serving_desc in CORRECTIONS
    ]

    session = SessionLocal()
    try:
        statement = insert(FoodNutrition).values(rows)
        set_ = {
            "kcal_per_serving": statement.excluded.kcal_per_serving,
            "serving_desc": statement.excluded.serving_desc,
            "source": statement.excluded.source,
        }
        # 기존 mfds/raw 행의 매크로·food_group 은 옛 서빙 기준이라 비운다.
        set_.update({column: None for column in _NULLED})
        # source 제한 없이 덮어쓴다 — 이게 seed_curated 와의 핵심 차이다.
        statement = statement.on_conflict_do_update(
            index_elements=[FoodNutrition.food_label],
            set_=set_,
        )
        session.execute(statement)
        session.commit()
        print(f"1인분 보정 {len(rows)}건 upsert 완료 (source={SOURCE_CURATED}).")
    finally:
        session.close()


if __name__ == "__main__":
    correct()
