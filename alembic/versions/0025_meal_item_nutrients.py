"""meal_items 영양 스냅샷 — 기록이 기록으로 남게

지금까지 하루 누적(28장)과 경고(16장)는 저장된 `food_label`로 `food_nutrition`을 **매번 다시
조회**해 수치를 만들었다. 그래서 DB 값이 바뀌면 **과거 기록이 말하는 수치도 소급해 바뀐다.**

2026-07-25에 그 일이 실제로 일어났다 — 1인분 기준을 4,536행 고치고(홀케이크·피자) 동명 행
선택 규칙도 바꿨는데(라면 226.6 g → 550 g), 그 순간 사용자의 지난 기록이 말하는 나트륨도
조용히 달라졌다. 기록이 아니라 추정이었던 것이다.

`docs/PRODUCT_STRATEGY.md` §0-1의 목표는 "판단에 쓸 근거를 **정확하게** 남긴다"이고, 그 근거는
**기록된 시점의 것**이어야 한다. 진료에서 되짚거나(§0-2 지표) 검사 수치 악화의 원인을 찾으려면
더욱 그렇다.

저장값은 **먹은 양 기준**이다 (1인분 실측 × `serving_ratio`). 실측이 없는 음식은 NULL 이고,
그 사실은 하루 누적의 `measured_items`로 이미 드러난다.

기존 행은 **현재 DB 값으로 백필**한다. 기록 당시 값이 아니라는 한계가 있지만, 비워 두면
조회 경로가 영구히 폴백을 안고 가야 한다. 사용자가 1명(제작자)인 지금이 백필 비용이 가장 싸다.

Revision ID: 0025_meal_item_nutrients
Revises: 0024_diabetes_sodium_tag
Create Date: 2026-07-25
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0025_meal_item_nutrients"
down_revision = "0024_diabetes_sodium_tag"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("sodium_mg", sa.Numeric(8, 1)),
    ("potassium_mg", sa.Numeric(8, 1)),
    ("phosphorus_mg", sa.Numeric(8, 1)),
    ("sugar_g", sa.Numeric(6, 1)),
)

# 기존 행 백필 — 정확 일치(공백 무시)만 쓴다. 경고 판정(`_measured_for_warning`)과 같은 규약이라
# "경고는 떴는데 합계에는 안 잡히는" 음식이 생기지 않는다. 유사도(trgm)는 쓰지 않는다.
_BACKFILL = """
    UPDATE meal_items AS mi
       SET sodium_mg     = ROUND(fn.sodium_mg     * mi.serving_ratio, 1),
           potassium_mg  = ROUND(fn.potassium_mg  * mi.serving_ratio, 1),
           phosphorus_mg = ROUND(fn.phosphorus_mg * mi.serving_ratio, 1),
           sugar_g       = ROUND(fn.sugar_g       * mi.serving_ratio, 1)
      FROM food_nutrition AS fn
     WHERE REPLACE(fn.food_label, ' ', '') = REPLACE(mi.food_label, ' ', '')
"""


def upgrade() -> None:
    for name, column_type in _COLUMNS:
        op.add_column("meal_items", sa.Column(name, column_type, nullable=True))

    op.execute(_BACKFILL)


def downgrade() -> None:
    for name, _type in _COLUMNS:
        op.drop_column("meal_items", name)
