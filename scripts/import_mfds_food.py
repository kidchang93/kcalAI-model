"""식약처 통합식품영양성분정보(음식) CSV → food_nutrition 임포트.

사용법 (반드시 저장소 루트에서):
    venv/bin/python scripts/import_mfds_food.py <원본 CSV 경로>

DATA_MODEL.md 12장 규칙:
- 원본 영양값은 100g/100ml 기준 → 1인분 = 원본값 × 식품중량 ÷ 기준량 (kcal 은 반올림 정수).
- 식품중량이 없으면 환산 없이 100g 기준으로 저장하고 serving_desc="100g당".
- 같은 식품명 중복은 식품중량 있는 행 우선 1행만 선택.
- idempotent upsert. source='llm'(추정) 행은 mfds(실측)가 덮어쓴다. curated 는 보존.
"""

import argparse
import csv
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert

# 스크립트를 scripts/ 밖의 로컬 모듈(database, models)과 연결한다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import SessionLocal  # noqa: E402
from models.health_model import FoodNutrition  # noqa: E402

SOURCE_MFDS = "mfds"
# mfds(실측)는 llm(추정)보다 우선하고, 재실행 시 자기 자신도 갱신한다. curated 는 감수 콘텐츠라 보존.
OVERWRITABLE_SOURCES = ("llm", SOURCE_MFDS)
BATCH_SIZE = 1000

_AMOUNT_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(g|ml|l)?\s*$", re.IGNORECASE)


def parse_amount(raw: str) -> tuple[Decimal, str] | None:
    """'291.90ml' → (Decimal('291.90'), 'ml'). 빈 값·비수치 문자열은 None."""
    match = _AMOUNT_PATTERN.match(raw or "")
    if match is None:
        return None
    value = Decimal(match.group(1))
    if value <= 0:
        return None
    unit = (match.group(2) or "g").lower()
    return value, unit


def parse_nutrient(raw: str) -> Decimal | None:
    if raw is None or raw.strip() == "":
        return None
    try:
        return Decimal(raw.strip())
    except InvalidOperation:
        return None


def scale(value: Decimal | None, factor: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    scaled = value if factor is None else value * factor
    return scaled.quantize(Decimal("0.1"))


def build_record(row: dict[str, str]) -> dict | None:
    """CSV 1행 → food_nutrition upsert 값. 에너지가 없으면 None (제외)."""
    energy = parse_nutrient(row["에너지(kcal)"])
    if energy is None:
        return None

    base = parse_amount(row["영양성분함량기준량"])  # "100g" / "100ml"
    serving = parse_amount(row["식품중량"])  # "291.90ml" 등, 12행 누락

    if base is not None and serving is not None:
        factor = serving[0] / base[0]
        serving_desc = f"1인분 (약 {round(serving[0])}{serving[1]})"
    else:
        # 식품중량 누락 행은 환산 없이 기준량(100g/100ml) 값 그대로 저장한다 (12장).
        factor = None
        serving_desc = "100g당"

    kcal = int((energy if factor is None else energy * factor).to_integral_value(rounding="ROUND_HALF_UP"))

    return {
        "food_label": row["식품명"].strip()[:100],
        "kcal_per_serving": kcal,
        "serving_desc": serving_desc[:100],
        "carbs_g": scale(parse_nutrient(row["탄수화물(g)"]), factor),
        "protein_g": scale(parse_nutrient(row["단백질(g)"]), factor),
        "fat_g": scale(parse_nutrient(row["지방(g)"]), factor),
        "sugar_g": scale(parse_nutrient(row["당류(g)"]), factor),
        "sodium_mg": scale(parse_nutrient(row["나트륨(mg)"]), factor),
        "potassium_mg": scale(parse_nutrient(row["칼륨(mg)"]), factor),
        "phosphorus_mg": scale(parse_nutrient(row["인(mg)"]), factor),
        "food_group": row["식품대분류명"].strip()[:30],
        "source": SOURCE_MFDS,
        # 중복 식품명 선택 기준 (upsert 전 dedupe 용, DB 에는 넣지 않는다).
        "_has_serving": serving is not None,
    }


def load_records(csv_path: Path) -> list[dict]:
    picked: dict[str, dict] = {}
    total_rows = 0
    skipped = 0

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            total_rows += 1
            record = build_record(row)
            if record is None:
                skipped += 1
                continue
            current = picked.get(record["food_label"])
            # 같은 식품명은 식품중량 있는 행 우선 1행. 동순위면 먼저 나온 행 유지 (재실행 결정성).
            if current is None or (record["_has_serving"] and not current["_has_serving"]):
                picked[record["food_label"]] = record

    records = list(picked.values())
    for record in records:
        del record["_has_serving"]

    print(f"원본 {total_rows}행 → 에너지 누락 제외 {skipped}행, 고유 식품명 {len(records)}건")
    return records


def upsert(records: list[dict]) -> None:
    table = FoodNutrition.__table__
    session = SessionLocal()
    try:
        for start in range(0, len(records), BATCH_SIZE):
            batch = records[start : start + BATCH_SIZE]
            statement = insert(table).values(batch)
            statement = statement.on_conflict_do_update(
                index_elements=[table.c.food_label],
                set_={
                    column: statement.excluded[column]
                    for column in (
                        "kcal_per_serving",
                        "serving_desc",
                        "carbs_g",
                        "protein_g",
                        "fat_g",
                        "sugar_g",
                        "sodium_mg",
                        "potassium_mg",
                        "phosphorus_mg",
                        "food_group",
                        "source",
                    )
                },
                where=table.c.source.in_(OVERWRITABLE_SOURCES),
            )
            session.execute(statement)
        session.commit()
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="식약처 음식 영양 CSV 를 food_nutrition 에 적재한다.")
    parser.add_argument("csv_path", type=Path, help="식약처 통합식품영양성분정보(음식) CSV 경로")
    args = parser.parse_args()

    if not args.csv_path.is_file():
        parser.error(f"CSV 파일을 찾을 수 없습니다: {args.csv_path}")

    records = load_records(args.csv_path)
    upsert(records)
    print(f"upsert 완료: {len(records)}건 (source={SOURCE_MFDS})")


if __name__ == "__main__":
    main()
