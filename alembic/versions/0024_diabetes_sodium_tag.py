"""condition_types: 당뇨에 low_sodium 태그 — KDA2025 권고 9

당뇨의 `dietary_tags`는 `['low_sugar','low_gi']`뿐이라 **나트륨 축이 돌지 않았다.** 경고 판정은
사용자 질병의 태그와 겹치는 축만 검사하므로(`nutrition_service.get_record_warnings`), 당뇨
사용자는 나트륨이 아무리 높은 음식을 기록해도 경고를 받지 못했다.

대한당뇨병학회 KDA2025 「5-3. 의학영양요법」 **권고 9**는 나트륨 하루 2,300 mg 이내를 명시한다
(RCT, 일반적권고). 등급 계산 쪽은 이미 당뇨를 포함해 두었으므로
(`chronic_food_rules.SODIUM_TIER_CONDITIONS`) 태그만 채우면 켜진다.

1인분 경계는 고혈압과 같은 값(높음 600 mg)을 쓴다. 고혈압 상한(2,000)이 당뇨(2,300)보다 낮아
당뇨에는 **보수적으로** 작동하며, 두 질환을 함께 가진 사용자에게 경계가 갈리지 않는다.

`low_gi`는 태그만 있고 축이 없다 — 혈당지수를 우리 DB 가 갖고 있지 않아서다
(`docs/CHRONIC_NUTRITION_SOURCES.md` §2-4). 태그를 지우지 않고 그대로 둔다.

Revision ID: 0024_diabetes_sodium_tag
Revises: 0023_ckd_stage
Create Date: 2026-07-25
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0024_diabetes_sodium_tag"
down_revision = "0023_ckd_stage"
branch_labels = None
depends_on = None

# `dietary_tags`는 텍스트 배열이 아니라 **jsonb** 다 (리비전 0005). 없을 때만 덧붙여
# 재실행해도 태그가 중복되지 않는다.
_ADD = """
    UPDATE condition_types
       SET dietary_tags = dietary_tags || '["low_sodium"]'::jsonb
     WHERE code = 'diabetes'
       AND NOT (dietary_tags @> '["low_sodium"]'::jsonb)
"""

_REMOVE = """
    UPDATE condition_types
       SET dietary_tags = dietary_tags - 'low_sodium'
     WHERE code = 'diabetes'
"""


def upgrade() -> None:
    op.execute(_ADD)


def downgrade() -> None:
    op.execute(_REMOVE)
