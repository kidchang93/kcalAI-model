"""여러 명이 나눠 먹는 제품이 "1인분"으로 들어온 행을 1회 섭취참고량으로 되돌린다.

## 무엇을 고치고, 무엇을 못 고치는가 (2026-07-25 실측으로 범위가 줄었다)

처음에는 "간식·음료의 1인분이 제품 한 통"이라 보고 식품군 단위로 캡을 씌우려 했다.
빵·과자류는 57%, 음료·차류는 72%가 400 g을 넘으니 근거는 충분해 보였다.
**dry-run 이 반례를 보여줬다:**

    홍차_잉글리쉬브렉퍼스트 아이스 (L)   473 ml   ← 카페 그란데 한 잔. **1인분이 맞다**
    햄버거_더오치 맥시멈 원파운더        606 g    ← 한 사람이 먹는다. **1인분이 맞다**
    케이크_화이트생크림 케이크 3호        740 g    ← 홀케이크. 나눠 먹는다
    피자_새우파티 피자 (R)              748 g    ← 한 판. 나눠 먹는다

즉 "1인분이 크다"와 "여러 명이 먹는다"는 다른 말이다. 식품군으로는 그 둘이 갈리지 않는다 —
'빵 및 과자류' 안에 햄버거(1인분)와 홀케이크(다인분)가 함께 있다. 캡을 일괄로 씌우면
그란데 한 잔을 200 ml로, 햄버거를 70 g으로 만들어 **오히려 더 틀린다.**

그래서 **제품명이 스스로 다인분임을 밝히는 것만** 고친다:

- 케이크 + 호수 표시(2호·3호·6호…) — 홀케이크는 조각으로 나눠 먹는다
- 피자 — 판 단위로 팔리고 조각으로 먹는다

나머지(일반 빵·과자·음료·빙과)는 **손대지 않는다.** 1인분인지 아닌지를 이름만으로 가릴 수
없고, 근거 없이 줄이면 사용자가 먹은 양보다 작게 기록된다. 이 한계는
`CHRONIC_NUTRITION_SOURCES.md` §2-5에 남긴다 — 당류 등급을 켜지 못하는 이유도 그대로다.

## 무엇을 근거로 고치나

**「식품등의 표시기준」[별표 3] 1회 섭취참고량** (법제처 현행 고시, 2026-07-25 확인).
정책값이 아니라 법정 기준이다.

    빵류 - 피자          150 g
    빵류 - 그 밖의 해당식품  70 g   ← 케이크 한 조각

## 어떻게 고치나

영양값은 1인분 기준으로 저장돼 있으므로(12장) 비율만 맞춘다:

    ratio = 참고량 / 현재_1인분_g
    kcal·탄수·단백·지방·당류·나트륨·칼륨·인 × ratio

멱등이다 — 이미 참고량 이하인 행은 건너뛴다. `source='curated'`(사람이 보정한 값)는 제외한다.

사용법: `venv/bin/python scripts/normalize_serving_size.py [--dry-run]`
"""

import argparse
import re
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from database import engine  # noqa: E402
from models.health_model import FoodNutrition  # noqa: E402

# [별표 3] 1회 섭취참고량 — 빵류
REFERENCE_PIZZA_G = 150
REFERENCE_BREAD_G = 70

# 케이크 호수 표시(1호~12호). "3호", "3 호", "3호케이크" 모두 잡는다.
CAKE_SIZE_PATTERN = re.compile(r"(?:^|[^0-9])([1-9]|1[0-2])\s*호(?![가-힣])")

# 비율을 곱할 컬럼 — 전부 1인분 기준 값이다.
SCALED_COLUMNS = (
    "carbs_g", "protein_g", "fat_g", "sugar_g", "sodium_mg", "potassium_mg", "phosphorus_mg",
)


def reference_for(label: str, food_group: str | None) -> tuple[int, str] | None:
    """다인분 제품이면 1회 섭취참고량, 아니면 None(손대지 않음).

    **분류 접두사로 판정한다.** 라벨은 `분류_상품명` 구조인데(`피자_흥부포테이토 피자`),
    부분 문자열로 '피자'를 찾으면 **피자빵**(빵 하나 200 g — 1인분이 맞다)과 그 분류에
    딸려 들어간 '와앙 보름달빵'까지 걸린다. 실제로 dry-run 에서 4,527건이 잡혔고 대부분이
    그 오탐이었다.
    """
    if food_group not in ("빵 및 과자류", "과자류·빵류 또는 떡류"):
        return None

    # 접두사가 없으면 라벨 전체를 분류로 본다 ('피자빵' 같은 단독 라벨).
    category = label.split("_", 1)[0].strip()

    if category == "피자":
        return REFERENCE_PIZZA_G, "빵류-피자"

    if category == "케이크" and CAKE_SIZE_PATTERN.search(label):
        return REFERENCE_BREAD_G, "빵류-그 밖(케이크 한 조각)"

    return None


def normalize(session: Session, dry_run: bool) -> None:
    rows = session.scalars(
        select(FoodNutrition).where(
            FoodNutrition.source != "curated",
            FoodNutrition.serving_size_g.is_not(None),
        )
    ).all()

    changed = 0
    already_ok = 0
    samples: list[str] = []

    for row in rows:
        matched = reference_for(row.food_label, row.food_group)

        if matched is None:
            continue

        amount, basis = matched
        current = Decimal(row.serving_size_g)

        if current <= amount:
            already_ok += 1
            continue

        ratio = Decimal(amount) / current
        new_kcal = int(round(row.kcal_per_serving * ratio))

        if len(samples) < 10:
            samples.append(
                f"  {row.food_label[:34]:36} {current:>7} g → {amount} g   "
                f"{row.kcal_per_serving:>5} → {new_kcal:>4} kcal  ({basis})"
            )

        if not dry_run:
            row.kcal_per_serving = new_kcal
            for column in SCALED_COLUMNS:
                value = getattr(row, column)
                if value is not None:
                    setattr(row, column, (Decimal(value) * ratio).quantize(Decimal("0.1")))
            row.serving_size_g = Decimal(amount).quantize(Decimal("0.1"))
            row.serving_desc = f"1회 섭취참고량 ({amount}g)"

        changed += 1

    print(f"전체 {len(rows)}행 검사")
    print(f"  교정 {changed}행 · 이미 참고량 이하 {already_ok}행")
    print("\n샘플:")
    for sample in samples:
        print(sample)

    if dry_run:
        print("\n--dry-run 이라 저장하지 않았습니다.")
        session.rollback()
    else:
        session.commit()
        print("\n저장했습니다.")


def main() -> None:
    parser = argparse.ArgumentParser(description="다인분 제품의 1인분을 1회 섭취참고량으로")
    parser.add_argument("--dry-run", action="store_true", help="저장하지 않고 결과만 본다")
    args = parser.parse_args()

    with Session(engine) as session:
        normalize(session, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
