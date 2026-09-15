"""식약처 임포트 스크립트(import_mfds_food·import_mfds_processed·import_mfds_raw) 공용 헬퍼.

import 전에 저장소 루트가 sys.path 에 있어야 한다 — 각 스크립트가 넣는다.
"""

from sqlalchemy.dialects.postgresql import insert

from database import SessionLocal
from models.health_model import FoodNutrition

BATCH_SIZE = 1000
COLUMNS = (
    "kcal_per_serving", "serving_desc", "serving_size_g",
    "carbs_g", "protein_g", "fat_g",
    "sugar_g", "sodium_mg", "potassium_mg", "phosphorus_mg",
    "food_group", "source",
)


def to_float(raw) -> float | None:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def upsert(records: list[dict], overwritable: tuple[str, ...]) -> None:
    """food_label 이 겹치면 기존 행의 source 가 overwritable 일 때만 덮는다. 나머지 source 는 보존."""
    table = FoodNutrition.__table__
    with SessionLocal() as session:
        for start in range(0, len(records), BATCH_SIZE):
            statement = insert(table).values(records[start : start + BATCH_SIZE])
            statement = statement.on_conflict_do_update(
                index_elements=[table.c.food_label],
                set_={column: statement.excluded[column] for column in COLUMNS},
                where=table.c.source.in_(overwritable),
            )
            session.execute(statement)
        session.commit()
