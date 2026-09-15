"""식약처 통합식품영양성분정보(음식) CSV → food_nutrition 임포트.

사용법 (반드시 저장소 루트에서):
    venv/bin/python scripts/import_mfds_food.py <원본 CSV 경로>

DATA_MODEL.md 12장 규칙:
- 원본 영양값은 100g/100ml 기준 → 1인분 = 원본값 × 식품중량 ÷ 기준량 (kcal 은 반올림 정수).
- 식품중량이 없으면 환산 없이 100g 기준으로 저장하고 serving_desc="100g당".
- **같은 식품명은 중복을 걷어낸 뒤 1인분 kcal 중앙 순위 행을 통째로 고른다** (아래).
- idempotent upsert. source='llm'(추정) 행은 mfds(실측)가 덮어쓴다. curated 는 보존.

## 동명 다중 행을 중앙값으로 집계하는 이유 (2026-07-25)

원본에는 같은 식품명이 여러 행으로 들어 있다 — 고유 15,568건 중 **1,717건(11%)**이 그렇고,
그중 1,382건은 **식품중량이 서로 다르다**(최대 19.7배 차이). 조리법·출처가 다른 실측이 같은
이름을 달고 있는 것이다.

예전 규칙은 "식품중량 있는 행 우선, 동순위면 먼저 나온 행"이었다. **CSV 순서가 값을 정한다는
뜻이고, 근거가 없다.** 실제로 그래서 라면이 226.6 ml 행으로 들어와 383 kcal·나트륨 290 mg 이
됐다 — 라면 국물 100 g(380 mg)보다 낮은 값이라 고나트륨 경고가 침묵했고, 2026-07-23에
`correct_common_foods.NUTRIENT_OVERRIDES`로 **손으로** 고쳐야 했다.

새 규칙은 **중복을 걷어낸 뒤 1인분 kcal 로 순위를 매겨 가운데 행을 통째로** 쓴다. 라면은
550 g 행이 되어 **수동 교정이 도달한 값과 같아진다** — 규칙이 사례를 자동으로 맞힌 것이라
근거로 삼을 만하다.

처음에는 영양소별 중앙값을 내려다 두 가지에 걸려 접었다:

- **완전 중복이 표를 나눠 갖는다.** 김치찌개는 200 ml/19 kcal 행(국물만 잰 값으로 보인다)이
  **4번**, 400 g/61 kcal 행이 1번 들어 있다. 중복을 그대로 세면 1인분이 38 kcal 이 된다.
- **값을 섞으면 없는 조합이 된다.** 영양소별 중앙값은 에너지를 A 행에서, 나트륨을 B 행에서
  가져온다. 행을 통째로 고르면 모든 값이 같은 실측에서 온다.

`import_mfds_processed.py`·`import_mfds_raw.py`는 **상품 단위 → 대표식품명 집계**라 성격이
다르다(중앙값 유지). 이 스크립트는 같은 이름의 여러 실측 중 하나를 고르는 문제다.

⚠️ **재임포트 후에는 후속 스크립트를 순서대로 다시 돌려야 한다** (이 스크립트가 mfds 행을
덮어쓰기 때문):
    1. `import_mfds_food.py`  ← 지금 이 스크립트
    2. `normalize_serving_size.py`  (홀케이크·피자 1인분)
    3. `correct_common_foods.py`    (자주 먹는 음식 1인분 보정)
    4. `backfill_curated_nutrients.py` (보정이 비운 영양소 되채우기)
"""

import argparse
import csv
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

# 스크립트를 scripts/ 밖의 로컬 모듈(database, models)과 연결한다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from food_upsert import upsert  # noqa: E402

SOURCE_MFDS = "mfds"
# mfds(실측)는 llm(추정)보다 우선하고, 재실행 시 자기 자신도 갱신한다. curated 는 감수 콘텐츠라 보존.
OVERWRITABLE_SOURCES = ("llm", SOURCE_MFDS)

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


_DEDUPE_COLUMNS = (
    "영양성분함량기준량", "식품중량", "에너지(kcal)", "탄수화물(g)", "단백질(g)",
    "지방(g)", "당류(g)", "나트륨(mg)", "칼륨(mg)", "인(mg)",
)


def serving_kcal(row: dict[str, str]) -> Decimal | None:
    """이 행이 말하는 1인분 kcal. 식품중량이 없으면 기준량(100g) 값 그대로."""
    energy = parse_nutrient(row.get("에너지(kcal)", ""))

    if energy is None:
        return None

    base = parse_amount(row.get("영양성분함량기준량", ""))
    serving = parse_amount(row.get("식품중량", ""))

    if base is None or serving is None:
        return energy

    return energy * serving[0] / base[0]


def merge_rows(rows: list[dict[str, str]]) -> dict[str, str] | None:
    """같은 식품명의 여러 행 → **대표 1행**. 값을 섞지 않고 행을 통째로 고른다.

    두 가지를 지킨다.

    **(1) 완전 중복은 1표만.** 원본에는 같은 값의 행이 여러 번 들어 있다 — 김치찌개는
    200 ml/19 kcal(국물만 잰 값으로 보인다) 행이 **4번** 있고 400 g/61 kcal 행이 1번 있다.
    중복을 그대로 세면 4표가 1표를 이겨 1인분이 38 kcal 이 된다.

    **(2) 값을 섞지 않는다.** 영양소별로 중앙값을 내면 에너지는 A 행에서, 나트륨은 B 행에서
    오는 **실제로 존재하지 않는 조합**이 만들어진다. 대신 1인분 kcal 로 순위를 매겨 가운데
    행을 통째로 쓴다 — 에너지·나트륨·중량이 같은 실측에서 온다.

    짝수 개면 **위쪽(큰 쪽)**을 고른다. 만성질환 맥락에서는 과소평가가 과대평가보다 위험하다
    (나트륨을 실제보다 적게 보면 경고가 침묵한다).

    실측 검증 (2026-07-25):
        라면    [226.6, 550, 590]      → 550 g 행 (수동 교정 NUTRIENT_OVERRIDES 와 같은 답)
        김치찌개 [400 g, 200 ml]        → 400 g 행 (중복 4행을 걷어낸 결과)
        막국수  [132.4, 632.4, 732.6]  → 732.6 ml 행
    """
    if len(rows) == 1:
        return rows[0]

    unique: dict[tuple, dict[str, str]] = {}
    for row in rows:
        unique.setdefault(tuple(row.get(name, "") for name in _DEDUPE_COLUMNS), row)

    ranked = [(kcal, row) for row in unique.values() if (kcal := serving_kcal(row)) is not None]

    if not ranked:
        return None

    ranked.sort(key=lambda item: item[0])

    return ranked[len(ranked) // 2][1]


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
        # 1인분 무게(g). 식품중량의 숫자를 그대로(ml 은 밀도≈1 로 g 취급).
        serving_size_g = serving[0].quantize(Decimal("0.1"))
    else:
        # 식품중량 누락 행은 환산 없이 기준량(100g/100ml) 값 그대로 저장한다 (12장).
        # "100g당" = 100g 기준값. 사용자가 g 을 입력하면 kcal × 입력g/100 으로 환산된다.
        factor = None
        serving_desc = "100g당"
        serving_size_g = Decimal("100")

    kcal = int((energy if factor is None else energy * factor).to_integral_value(rounding="ROUND_HALF_UP"))

    return {
        "food_label": row["식품명"].strip()[:100],
        "kcal_per_serving": kcal,
        "serving_desc": serving_desc[:100],
        "serving_size_g": serving_size_g,
        "carbs_g": scale(parse_nutrient(row["탄수화물(g)"]), factor),
        "protein_g": scale(parse_nutrient(row["단백질(g)"]), factor),
        "fat_g": scale(parse_nutrient(row["지방(g)"]), factor),
        "sugar_g": scale(parse_nutrient(row["당류(g)"]), factor),
        "sodium_mg": scale(parse_nutrient(row["나트륨(mg)"]), factor),
        "potassium_mg": scale(parse_nutrient(row["칼륨(mg)"]), factor),
        "phosphorus_mg": scale(parse_nutrient(row["인(mg)"]), factor),
        "food_group": row["식품대분류명"].strip()[:30],
        "source": SOURCE_MFDS,
    }


def load_records(csv_path: Path) -> list[dict]:
    """같은 식품명의 행들을 모아 중앙값 1건으로 집계한다 (docstring 상단 참조)."""
    grouped: dict[str, list[dict[str, str]]] = {}
    total_rows = 0

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            total_rows += 1
            label = (row.get("식품명") or "").strip()

            if label:
                grouped.setdefault(label[:100], []).append(row)

    records: list[dict] = []
    skipped = 0
    merged_count = 0

    for rows in grouped.values():
        if len(rows) > 1:
            merged_count += 1

        merged = merge_rows(rows)
        record = None if merged is None else build_record(merged)

        if record is None:
            skipped += 1
            continue

        records.append(record)

    print(
        f"원본 {total_rows}행 → 고유 식품명 {len(grouped)}건 "
        f"(동명 다중 {merged_count}건은 중복 제거 후 대표 행 선택), 에너지 누락 제외 {skipped}건 "
        f"→ 적재 {len(records)}건"
    )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="식약처 음식 영양 CSV 를 food_nutrition 에 적재한다.")
    parser.add_argument("csv_path", type=Path, help="식약처 통합식품영양성분정보(음식) CSV 경로")
    args = parser.parse_args()

    if not args.csv_path.is_file():
        parser.error(f"CSV 파일을 찾을 수 없습니다: {args.csv_path}")

    records = load_records(args.csv_path)
    upsert(records, OVERWRITABLE_SOURCES)
    print(f"upsert 완료: {len(records)}건 (source={SOURCE_MFDS})")


if __name__ == "__main__":
    main()
