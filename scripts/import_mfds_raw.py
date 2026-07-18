"""식약처 통합 원재료성식품 CSV(농진청·해수부) → food_nutrition 선별 임포트.

사용법 (반드시 저장소 루트에서, 여러 파일 한 번에):
    venv/bin/python scripts/import_mfds_raw.py <원재료성 CSV 경로>...

원물 과일·채소·견과·수산물을 보강한다 (DATA_MODEL.md 14장) — 음식(요리)·가공식품
DB 가 못 덮는 마지막 영역. estimate 조회 전용이며 추천에는 들어가지 않는다.

- 행은 분석 변형 단위("포도_거봉_생것", "가리비류_…_관자_생것_평균")라 **일반명
  단위 중앙값**으로 집계한다. 키는 식품중분류명과 대표식품명 **양쪽**에 잡는다 —
  농진청은 품종이 중분류라(거봉·캠벨얼리) 중분류만 쓰면 "포도" 키에 말린것(건포도
  297kcal)만 남는 오염이 실측됐다. "가리비류" 같은 꼬리 '류'와 "(착색단고추)" 같은
  괄호 표기는 뗀다 — 괄호를 안 떼면 조미료 분말이 "파프리카" 키를 차지한다.
- 상태 선택: 촬영 대상은 조리 전 원물이므로 **'생것' 행 우선**(없으면 전체 —
  곶감처럼 말린 것이 본체인 키가 있다). 차류만 예외로 **'추출/용액'만** 쓴다 —
  말린 잎(100g 당 ~380kcal)을 찻잔 kcal 로 주면 안 된다. 추출 행이 없는 차 키는 버린다.
- 이 CSV 에는 식품중량·1회 섭취참고량이 없어 전부 "100g당"으로 적재한다.
- source='mfds_raw'. 기존 mfds(요리)·curated·mfds_processed 행은 건드리지 않는다.
- idempotent upsert (재실행 시 자기 자신만 갱신).
"""

import argparse
import re
import statistics
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import SessionLocal  # noqa: E402
from models.health_model import FoodNutrition  # noqa: E402

import csv  # noqa: E402

SOURCE_RAW = "mfds_raw"
OVERWRITABLE_SOURCES = ("llm", SOURCE_RAW)
BATCH_SIZE = 1000

# 원물 라벨이 기름으로 오폭한다(포도→포도씨유). 가공식품 임포트와 같은 이유.
EXCLUDED_GROUPS = frozenset({"유지류"})

TEA_GROUP = "차류"
TEA_STATES = ("추출", "용액")

NUTRIENT_COLUMNS = {
    "carbs": "탄수화물(g)",
    "protein": "단백질(g)",
    "fat": "지방(g)",
    "sugar": "당류(g)",
    "sodium": "나트륨(mg)",
    "potassium": "칼륨(mg)",
    "phosphorus": "인(mg)",
}


def to_float(raw) -> float | None:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def clean_name(name: str) -> str:
    name = re.sub(r"\([^)]*\)", "", name).strip()
    if len(name) > 2 and name.endswith("류"):
        name = name[:-1]
    return name


def key_names(row: dict[str, str]) -> set[str]:
    names = {clean_name(row["대표식품명"].strip())}
    mid = row["식품중분류명"].strip()
    if mid and mid != "해당없음":
        names.add(clean_name(mid))
    names.discard("")
    return names


def collect(csv_paths: list[Path]) -> dict[str, dict]:
    buckets: dict[str, dict] = {}
    total = 0
    for path in csv_paths:
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                total += 1
                group = row["식품대분류명"].strip()
                names = key_names(row)
                kcal = to_float(row["에너지(kcal)"])
                if not names or group in EXCLUDED_GROUPS or kcal is None:
                    continue

                food_name = row["식품명"]
                if group == TEA_GROUP and not any(s in food_name for s in TEA_STATES):
                    continue

                entry = {"kcal": kcal}
                for key, column in NUTRIENT_COLUMNS.items():
                    entry[key] = to_float(row.get(column))
                for name in names:
                    bucket = buckets.setdefault(name, {"group": group, "raw": [], "all": []})
                    bucket["all"].append(entry)
                    if "생것" in food_name:
                        bucket["raw"].append(entry)

    print(f"원본 {total}행 → 일반명 {len(buckets)}종 (유지류·추출 없는 차 제외)")
    return buckets


def build_records(buckets: dict[str, dict]) -> list[dict]:
    records = []
    for name, bucket in buckets.items():
        entries = bucket["raw"] or bucket["all"]

        def median_of(key: str) -> Decimal | None:
            values = [e[key] for e in entries if e[key] is not None]
            if not values:
                return None
            return Decimal(str(statistics.median(values))).quantize(Decimal("0.1"))

        kcal = int(Decimal(str(statistics.median(e["kcal"] for e in entries)))
                   .to_integral_value(rounding="ROUND_HALF_UP"))
        records.append({
            "food_label": name[:100],
            "kcal_per_serving": kcal,
            "serving_desc": "100g당",
            # "100g당" = 100g 기준값. 사용자가 g 을 입력하면 kcal × 입력g/100 으로 환산된다.
            "serving_size_g": Decimal("100"),
            "carbs_g": median_of("carbs"),
            "protein_g": median_of("protein"),
            "fat_g": median_of("fat"),
            "sugar_g": median_of("sugar"),
            "sodium_mg": median_of("sodium"),
            "potassium_mg": median_of("potassium"),
            "phosphorus_mg": median_of("phosphorus"),
            "food_group": bucket["group"][:30],
            "source": SOURCE_RAW,
        })
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
                        "kcal_per_serving", "serving_desc", "serving_size_g",
                        "carbs_g", "protein_g", "fat_g",
                        "sugar_g", "sodium_mg", "potassium_mg", "phosphorus_mg",
                        "food_group", "source",
                    )
                },
                # 요리 실측(mfds)·감수(curated)·가공식품 집계(mfds_processed)는 덮지 않는다.
                where=table.c.source.in_(OVERWRITABLE_SOURCES),
            )
            session.execute(statement)
        session.commit()
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="원재료성식품 CSV 를 food_nutrition 에 선별 적재한다.")
    parser.add_argument("csv_paths", type=Path, nargs="+", help="원재료성식품 CSV 경로 (복수 가능)")
    args = parser.parse_args()

    for path in args.csv_paths:
        if not path.is_file():
            parser.error(f"CSV 파일을 찾을 수 없습니다: {path}")

    records = build_records(collect(args.csv_paths))
    upsert(records)
    print(f"upsert 완료: {len(records)}건 (source={SOURCE_RAW})")


if __name__ == "__main__":
    main()
