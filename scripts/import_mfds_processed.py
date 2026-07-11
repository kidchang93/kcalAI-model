"""식약처 가공식품 DB(xlsx) → food_nutrition 선별 임포트.

사용법 (반드시 저장소 루트에서):
    venv/bin/python scripts/import_mfds_processed.py <가공식품 xlsx 경로>

음식(요리) DB가 못 덮는 영역(음료·주류·과자·조미료 등)을 보강한다 (DATA_MODEL.md 14장):
- 상품 단위(29.8만 행)가 아니라 **대표식품명 단위 일반 항목**으로 집계한다 —
  브랜드 상품명은 인식 라벨과 이어질 수 없고, 상품별 영양값의 중앙값이 대표값이다.
- 100g/100ml 기준값의 중앙값 → 1회 섭취참고량 중앙값으로 1회 제공량 환산.
- source='mfds_processed'. 같은 이름의 기존 mfds(요리)·curated 행은 건드리지 않는다 —
  요리 실측이 가공식품 집계보다 우선이다.
- 추천 후보 풀은 음식 DB 대분류 화이트리스트라 이 행들은 추천에 들어가지 않는다 (13장).
- idempotent upsert (재실행 시 자기 자신만 갱신).
"""

import argparse
import re
import statistics
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

import openpyxl
from sqlalchemy.dialects.postgresql import insert

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from database import SessionLocal  # noqa: E402
from models.health_model import FoodNutrition  # noqa: E402

SOURCE_PROCESSED = "mfds_processed"
OVERWRITABLE_SOURCES = ("llm", SOURCE_PROCESSED)
BATCH_SIZE = 1000

# 열 인덱스 (0-기준, 2026-06-26 배포본 실측).
COL_GROUP = 7  # 식품대분류명
COL_REP_NAME = 9  # 대표식품명
COL_BASE = 16  # 영양성분함량기준량 (항상 100g/100ml)
COL_KCAL = 17
COL_PROTEIN = 19
COL_FAT = 20
COL_CARBS = 22
COL_SUGAR = 23
COL_PHOSPHORUS = 27
COL_POTASSIUM = 28
COL_SODIUM = 29
COL_SERVING = 152  # 1회 섭취참고량

# 원물 라벨이 기름으로 오폭한다(포도→포도씨유 800kcal). 특수식은 촬영 대상이 아니다.
EXCLUDED_GROUPS = frozenset({"식용유지류", "특수영양식품", "특수의료용도식품"})

# 인식 라벨과 이름이 같지만 실물이 다른 원료 카테고리 — "코코아" 사진은 음료인데
# 이 카테고리들은 분말·원료(100g당 412~578kcal)라 음식 DB 매칭을 가로챈다.
EXCLUDED_REP_NAMES = frozenset({"코코아", "코코아매스"})

# "30g" · "200ml" · "5g(ml)" · "250ml(g)". 복합 표기("드레싱 15g, …")는 버린다.
_SERVING_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(g|ml|l)?(?:\((?:g|ml)\))?\s*$", re.IGNORECASE)


def parse_serving(raw) -> tuple[float, str] | None:
    match = _SERVING_PATTERN.match(str(raw or ""))
    if match is None:
        return None
    value = float(match.group(1))
    if value <= 0:
        return None
    return value, (match.group(2) or "g").lower()


def to_float(raw) -> float | None:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def median_or_none(values: list[float]) -> Decimal | None:
    if not values:
        return None
    return Decimal(str(statistics.median(values))).quantize(Decimal("0.1"))


def collect(xlsx_path: Path) -> dict[str, dict]:
    """대표식품명 → 상품별 값 리스트. 제외 대분류·'기타' 계열·에너지 누락은 건너뛴다."""
    workbook = openpyxl.load_workbook(xlsx_path, read_only=True)
    sheet = workbook.active

    buckets: dict[str, dict] = {}
    total = 0
    for row in sheet.iter_rows(min_row=2, values_only=True):
        total += 1
        group = str(row[COL_GROUP] or "").strip()
        name = str(row[COL_REP_NAME] or "").strip()
        kcal = to_float(row[COL_KCAL])
        if (not name or name.startswith("기타") or name in EXCLUDED_REP_NAMES
                or group in EXCLUDED_GROUPS or kcal is None):
            continue

        bucket = buckets.setdefault(
            name,
            {"group": group, "count": 0, "kcal": [], "carbs": [], "protein": [], "fat": [],
             "sugar": [], "sodium": [], "potassium": [], "phosphorus": [], "servings": []},
        )
        bucket["count"] += 1
        bucket["kcal"].append(kcal)
        for key, col in (("carbs", COL_CARBS), ("protein", COL_PROTEIN), ("fat", COL_FAT),
                         ("sugar", COL_SUGAR), ("sodium", COL_SODIUM),
                         ("potassium", COL_POTASSIUM), ("phosphorus", COL_PHOSPHORUS)):
            value = to_float(row[col])
            if value is not None:
                bucket[key].append(value)
        serving = parse_serving(row[COL_SERVING])
        if serving is not None:
            bucket["servings"].append(serving)

    workbook.close()
    print(f"원본 {total}행 → 대표식품 {len(buckets)}종 (제외 대분류·기타·에너지 누락 제외)")
    return buckets


def build_records(buckets: dict[str, dict]) -> list[dict]:
    """집계 → upsert 값. '비스킷/쿠키/크래커' 같은 복합명은 이름별 행으로 분리한다."""
    picked: dict[str, tuple[int, dict]] = {}

    for name, bucket in buckets.items():
        if bucket["servings"]:
            unit = Counter(u for _, u in bucket["servings"]).most_common(1)[0][0]
            amounts = [v for v, u in bucket["servings"] if u == unit]
            serving_value = statistics.median(amounts)
            factor = Decimal(str(serving_value)) / Decimal("100")  # 기준량은 항상 100g/100ml
            serving_desc = f"1회 제공량 (약 {round(serving_value)}{unit})"
        else:
            factor = None
            serving_desc = "100g당"

        kcal_base = Decimal(str(statistics.median(bucket["kcal"])))
        kcal = int((kcal_base if factor is None else kcal_base * factor)
                   .to_integral_value(rounding="ROUND_HALF_UP"))

        def scaled(key: str) -> Decimal | None:
            base = median_or_none(bucket[key])
            if base is None:
                return None
            return (base if factor is None else base * factor).quantize(Decimal("0.1"))

        record = {
            "kcal_per_serving": kcal,
            "serving_desc": serving_desc[:100],
            "carbs_g": scaled("carbs"),
            "protein_g": scaled("protein"),
            "fat_g": scaled("fat"),
            "sugar_g": scaled("sugar"),
            "sodium_mg": scaled("sodium"),
            "potassium_mg": scaled("potassium"),
            "phosphorus_mg": scaled("phosphorus"),
            "food_group": bucket["group"][:30],
            "source": SOURCE_PROCESSED,
        }

        # 복합명 분리 — 인식 라벨은 "크래커"지 "비스킷/쿠키/크래커"가 아니다.
        # 분리된 이름이 다른 대표식품과 겹치면 상품 수가 많은 쪽을 쓴다 (재실행 결정성).
        for part in (p.strip() for p in name.split("/")):
            if not part:
                continue
            current = picked.get(part)
            if current is None or bucket["count"] > current[0]:
                picked[part] = (bucket["count"], {"food_label": part[:100], **record})

    return [record for _, record in picked.values()]


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
                        "kcal_per_serving", "serving_desc", "carbs_g", "protein_g", "fat_g",
                        "sugar_g", "sodium_mg", "potassium_mg", "phosphorus_mg",
                        "food_group", "source",
                    )
                },
                # mfds(요리 실측)·curated 는 절대 덮지 않는다.
                where=table.c.source.in_(OVERWRITABLE_SOURCES),
            )
            session.execute(statement)
        session.commit()
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="식약처 가공식품 xlsx 를 food_nutrition 에 선별 적재한다.")
    parser.add_argument("xlsx_path", type=Path, help="식약처 가공식품 DB xlsx 경로")
    args = parser.parse_args()

    if not args.xlsx_path.is_file():
        parser.error(f"xlsx 파일을 찾을 수 없습니다: {args.xlsx_path}")

    records = build_records(collect(args.xlsx_path))
    upsert(records)
    print(f"upsert 완료: {len(records)}건 (source={SOURCE_PROCESSED})")


if __name__ == "__main__":
    main()
