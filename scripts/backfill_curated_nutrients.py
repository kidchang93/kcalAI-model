"""curated 행의 결측 영양소를 원본 공공 DB에서 되채운다 (kcal·serving 은 건드리지 않는다).

## 왜 필요한가 (2026-07-22)

`correct_common_foods.py` 가 1인분 kcal 을 현실화하면서 `_NULLED` 로 **나트륨·칼륨·인을 포함한
영양소 7종을 비운다.** "옛 서빙 기준의 값이 새 1인분과 불일치한다"는 이유 자체는 옳지만, 결과적으로
`source='curated'` 99행 — 된장찌개·설렁탕·육개장·미역국·갈비탕 같은 **국·탕·찌개와 사과·바나나 등
과일** — 의 영양소가 통째로 사라졌다.

그 대가는 경고의 침묵이다. 신장병 환자가 된장찌개를 기록해도 칼륨·인 경고가 나가지 않고(이미
운영 중이던 결함), 고혈압 나트륨 등급도 같은 음식에서 무력하다.

## 무엇을 하는가

원본 공공 CSV(100g/100ml 기준)에서 같은 이름을 찾아 **현재 `serving_size_g` 로 환산**해 채운다.
kcal 비율이 아니라 **무게 비율**로 환산하는 것이 핵심이다 — 나트륨은 칼로리가 아니라 무게에 비례한다.
(그래서 보정된 kcal 과 원본 kcal 이 달라도 영양소 환산은 영향받지 않는다.)

- **정확 일치만 쓴다.** 유사도(trgm)·부분 문자열 매칭을 쓰지 않는다 — 이름이 비슷한 다른 음식의
  칼륨으로 "높다"고 알리면 틀린 경고가 되고, 경고는 한 번 틀리면 전부 무시된다
  (`nutrition_service.measured_nutrition_for` 와 같은 규약).
- 같은 이름의 원본이 여러 행이면 **중앙값**을 쓴다 (`import_mfds_processed.py` 와 같은 방식).
- **이미 값이 있는 행은 건드리지 않는다** (`sodium_mg IS NULL` 인 curated 행만 대상).
- kcal·serving_desc·serving_size_g·source 는 **변경하지 않는다.**

## 실행

    venv/bin/python scripts/backfill_curated_nutrients.py --dry-run   # 변경 없이 리포트만
    venv/bin/python scripts/backfill_curated_nutrients.py             # 실제 UPDATE

멱등하다(재실행해도 이미 채워진 행은 대상에서 빠진다).

⚠️ **`correct_common_foods.py` 를 다시 돌리면 영양소가 또 비워진다.** 그 스크립트 실행 후에는
반드시 이 스크립트를 이어서 실행한다.
"""

import argparse
import csv
import statistics
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select, update

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import SessionLocal  # noqa: E402
from models.health_model import FoodNutrition  # noqa: E402

# 원본 공공 DB. 전부 같은 컬럼 규약(영양성분함량기준량 100g/100ml, 대표식품명·식품명)을 쓴다.
SOURCE_CSVS = (
    "식품의약품안전처_통합식품영양성분정보(음식)_20260429.csv",
    "농촌진흥청_국립식량과학원_통합식품영양성분정보(원재료성식품)_20251223.csv",
    "해양수산부_국립수산과학원_통합식품영양성분정보(원재료성식품)_20260113.csv",
)

# CSV 컬럼 → food_nutrition 컬럼. 전부 100g/100ml 기준값이다.
NUTRIENT_COLUMNS = {
    "carbs_g": "탄수화물(g)",
    "protein_g": "단백질(g)",
    "fat_g": "지방(g)",
    "sugar_g": "당류(g)",
    "sodium_mg": "나트륨(mg)",
    "potassium_mg": "칼륨(mg)",
    "phosphorus_mg": "인(mg)",
}

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 우리 curated 라벨 → 식약처 표기 (2026-08-03).
#
# **유사 매칭이 아니다.** 정확 일치만 쓴다는 원칙은 그대로이고(유사도를 허용하면 바나나에
# '말린것'이 섞여 칼륨이 2배가 된다), 여기 있는 것은 **사람이 원본 CSV 를 직접 확인한 1:1
# 대응**이다. 확인하지 못한 것은 넣지 않는다 — 비어 있는 편이 틀린 값보다 낫다.
#
# 왜 필요했나: `docs/PRODUCT_STRATEGY.md` §5-2 는 남은 71건을 "외국 요리·가공식품이라 원본이
# 없다"고 진단했는데 **틀렸다.** 목록에 계란찜·계란말이·북엇국·돈까스 같은 한식이 섞여 있었고,
# 원인은 원본 부재가 아니라 **표기 차이**였다. 계란찜은 원본에 `달걀찜`으로 멀쩡히 있다.
# 그 오진 때문에 "고칠 수 없는 일"로 분류돼 CKD 환자가 계란찜을 기록해도 인·칼륨 경고가
# 침묵하고 있었다.
LABEL_ALIASES = {
    "계란찜": "달걀찜",
    "계란말이": "달걀말이",
    "돈까스": "돈가스",
    "돼지고기수육": "수육",
    "알타리김치": "총각김치",
    "북엇국": "북어국",
    "소바": "메밀소바",
}

# 검토했으나 **넣지 않은 것** — 다음에 같은 후보를 다시 검토하지 않도록 이유를 남긴다.
#   보쌈 → 보쌈김치      : 고기 요리와 김치다. 완전히 다른 음식
#   무김치 → 깍두기      : 깍두기는 무김치의 한 종류일 뿐 대표하지 못한다
#   새우매운탕 → 매운탕  : 원본 '매운탕'은 생선 기준이라 재료가 다르다
#   회 → 모듬회          : '회'가 너무 일반적이라 어느 어종인지 정해지지 않는다
#   스튜 → 소고기스튜    : 〃


def parse_decimal(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    text = raw.strip().replace(",", "")
    if not text or text in {"-", "N/A"}:
        return None
    try:
        return Decimal(text)
    except Exception:
        return None


def parse_base_amount(raw: str | None) -> Decimal | None:
    """"100g" / "100ml" → 100. 숫자를 못 뽑으면 None."""
    if raw is None:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit() or ch == ".")
    value = parse_decimal(digits)
    return value if value and value > 0 else None


def load_source_index(data_dir: Path) -> dict[str, list[dict]]:
    """이름 → 원본 행들. 대표식품명과 식품명 양쪽으로 넣는다(정확 일치용).

    **원본이 하나도 없으면 실패한다.** 예전에는 "없음, 건너뜀"을 찍고 0건을 채운 뒤
    성공한 것처럼 끝났다 — 2026-07-25에 운영 서버(원본 CSV 를 두지 않는다)에서 재임포트
    파이프라인을 돌렸을 때 `correct_common_foods`가 비운 영양소를 이 스크립트가 못 채웠고,
    curated 100행의 나트륨·칼륨이 전부 비어 CKD·고혈압 경고가 다시 침묵했다.
    (2026-07-22 사건과 같은 구조가 도구 부재로 재발한 것이다.)

    운영에서는 로컬에서 `--emit-sql` 로 뽑은 SQL 을 적용한다.
    """
    index: dict[str, list[dict]] = {}
    missing: list[str] = []

    for filename in SOURCE_CSVS:
        path = data_dir / filename
        if not path.exists():
            missing.append(filename)
            print(f"  ! 원본 없음, 건너뜀: {filename}")
            continue

        with path.open(encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                # 나트륨조차 없는 행은 채울 것이 없다.
                if parse_decimal(row.get("나트륨(mg)")) is None:
                    continue
                for key in (row.get("대표식품명", ""), row.get("식품명", "")):
                    name = key.strip()
                    if name:
                        index.setdefault(name, []).append(row)

    if len(missing) == len(SOURCE_CSVS):
        raise SystemExit(
            "원본 CSV 를 하나도 찾지 못했습니다 — 채울 것이 없으니 **중단합니다**.\n"
            f"  찾은 위치: {data_dir}\n"
            "  운영 서버라면 이 스크립트를 직접 돌리지 말고, 로컬에서\n"
            "  `--emit-sql <경로>` 로 뽑은 SQL 을 적용하세요 (CLAUDE.md).\n"
            "  그냥 두면 correct_common_foods 가 비운 나트륨·칼륨·인이 채워지지 않아\n"
            "  국·탕·찌개·과일에서 CKD·고혈압 경고가 조용히 침묵합니다."
        )

    return index


def median_per_100(rows: list[dict]) -> dict[str, Decimal] | None:
    """같은 이름의 원본 행들에서 100g 기준 영양소 중앙값. 기준량이 없는 행은 제외.

    **'생것' 행이 있으면 그것만 쓴다** (`import_mfds_raw.py` 와 같은 규약). 원물은 같은 이름
    아래 건조·가공 변형이 섞여 있어서, 그대로 중앙값을 내면 값이 튄다 — 실측으로 확인한 사례:
    바나나에 '생것'(K 355mg)과 '말린것'(K 1,300mg)이 섞여 중앙값이 827mg으로 잡혔다.
    신장병 환자에게 바나나 칼륨을 2배 넘게 부풀려 알리게 된다.
    """
    fresh = [row for row in rows if "생것" in row.get("식품명", "")]
    rows = fresh or rows

    per_100: dict[str, list[Decimal]] = {column: [] for column in NUTRIENT_COLUMNS}

    for row in rows:
        base = parse_base_amount(row.get("영양성분함량기준량"))
        if base is None:
            continue

        for column, source_column in NUTRIENT_COLUMNS.items():
            value = parse_decimal(row.get(source_column))
            if value is not None:
                # 기준량이 100이 아닐 수도 있으므로 100g 기준으로 정규화한다.
                per_100[column].append(value * 100 / base)

    if not per_100["sodium_mg"]:
        return None

    return {
        column: Decimal(statistics.median(values)).quantize(Decimal("0.1"))
        for column, values in per_100.items()
        if values
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="curated 행의 결측 영양소 되채우기")
    parser.add_argument("--dry-run", action="store_true", help="변경 없이 리포트만 출력")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    # 운영 서버에는 원본 CSV 가 없다(커밋하지 않는 파일). 로컬에서 계산한 값을 SQL 로 뽑아
    # 운영에 적용한다 — serving_size_g 재임포트 때 쓴 방식과 같다.
    parser.add_argument("--emit-sql", type=Path, help="UPDATE 문을 파일로 출력 (DB 변경 없음)")
    args = parser.parse_args()

    print(f"원본 로드: {args.data_dir}")
    index = load_source_index(args.data_dir)
    print(f"  이름 {len(index):,}종")

    with SessionLocal() as session:
        # SQL 생성 모드는 **다른 환경(운영)에 적용할 문장**을 만드는 것이라, 로컬이 이미 채워져
        # 있어도 curated 전체를 계산 대상으로 삼는다. 실제 적용 여부는 생성된 SQL 의 WHERE
        # (`sodium_mg IS NULL`)가 대상 환경에서 판단한다.
        conditions = [FoodNutrition.source == "curated"]
        if not args.emit_sql:
            conditions.append(FoodNutrition.sodium_mg.is_(None))

        targets = session.execute(
            select(
                FoodNutrition.id,
                FoodNutrition.food_label,
                FoodNutrition.serving_size_g,
            ).where(*conditions)
        ).all()

        label = "curated 전체" if args.emit_sql else "curated + 나트륨 결측"
        print(f"대상({label}): {len(targets)}건")

        filled, skipped_no_source, skipped_no_size = 0, [], []
        used_aliases: list[str] = []
        sql_lines: list[str] = []

        for row_id, label, serving_size_g in targets:
            source_rows = index.get(label)

            # 이름이 그대로 없으면 **확인된 별칭**으로 한 번 더 찾는다 (LABEL_ALIASES).
            if not source_rows:
                alias = LABEL_ALIASES.get(label)
                if alias:
                    source_rows = index.get(alias)
                    if source_rows:
                        used_aliases.append(f"{label}→{alias}")

            if not source_rows:
                skipped_no_source.append(label)
                continue

            if serving_size_g is None or serving_size_g <= 0:
                # 1인분 무게를 모르면 환산할 수 없다. 100g 기준으로 넣으면 1인분과 뒤섞인다.
                skipped_no_size.append(label)
                continue

            per_100 = median_per_100(source_rows)
            if per_100 is None:
                skipped_no_source.append(label)
                continue

            factor = Decimal(serving_size_g) / 100
            values = {
                column: (amount * factor).quantize(Decimal("0.1"))
                for column, amount in per_100.items()
            }

            if args.emit_sql:
                assignments = ", ".join(f"{column} = {amount}" for column, amount in values.items())
                # food_label 로 매칭한다 — id 는 환경마다 다르다. 작은따옴표는 SQL 규약대로 이스케이프.
                escaped = label.replace("'", "''")
                sql_lines.append(
                    f"UPDATE food_nutrition SET {assignments} "
                    f"WHERE food_label = '{escaped}' AND source = 'curated' AND sodium_mg IS NULL;"
                )
            elif args.dry_run:
                print(
                    f"  {label}: 1인분 {serving_size_g}g → "
                    f"Na {values.get('sodium_mg')}mg · K {values.get('potassium_mg')}mg · "
                    f"P {values.get('phosphorus_mg')}mg"
                )
            else:
                session.execute(
                    update(FoodNutrition).where(FoodNutrition.id == row_id).values(**values)
                )

            filled += 1

        if args.emit_sql:
            session.rollback()
            args.emit_sql.write_text(
                "-- curated 결측 영양소 되채우기 (scripts/backfill_curated_nutrients.py --emit-sql)\n"
                "-- 원본: 식약처 음식 · 농진청/해수부 원재료성식품 CSV. 100g 기준 → serving_size_g 환산.\n"
                "BEGIN;\n" + "\n".join(sql_lines) + "\nCOMMIT;\n",
                encoding="utf-8",
            )
            print(f"\nSQL {len(sql_lines)}건 → {args.emit_sql}")
        elif args.dry_run:
            session.rollback()
        else:
            session.commit()

        mode = "[dry-run] " if args.dry_run else ("[emit-sql] " if args.emit_sql else "")
        print(f"\n{mode}채움: {filled}건")

        if used_aliases:
            # 별칭으로 찾은 것은 **드러내 놓는다** — 어떤 이름이 어떤 원본으로 채워졌는지
            # 보이지 않으면 잘못된 대응이 조용히 굳는다.
            print(f"  별칭 사용 {len(used_aliases)}건: {', '.join(used_aliases)}")

        if skipped_no_size:
            print(f"건너뜀(1인분 무게 없음) {len(skipped_no_size)}건: {', '.join(skipped_no_size)}")

        if skipped_no_source:
            # 원본에 그 이름이 없고 확인된 별칭도 없는 라벨. 유사 매칭으로 억지로 채우지 않는다.
            # 다만 "원본이 없다"고 단정하지 말 것 — 표기가 다를 뿐인 경우가 섞여 있다
            # (2026-08-03에 계란찜→달걀찜 등 7건이 그렇게 발견됐다, LABEL_ALIASES 주석).
            print(f"건너뜀(이름 못 찾음) {len(skipped_no_source)}건: {', '.join(skipped_no_source)}")


if __name__ == "__main__":
    main()
