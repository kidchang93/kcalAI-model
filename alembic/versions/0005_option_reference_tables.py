"""option reference tables + seed

DATA_MODEL.md 10장의 선택지 참조 테이블 (v2 3차 구현분):
condition_types, allergen_types 생성 + 시드, 기존 user_conditions.condition /
user_allergies.allergen 에 FK 연결. user_allergies.allergen 은 지금까지
한국어 자유 문자열이었으므로 label_ko → code 로 변환하고 매핑 불가 행은
삭제한다 (로컬 dev 데이터뿐, 재온보딩으로 복구 가능).

Revision ID: 0005_option_reference_tables
Revises: 0004_group_pet_tables
Create Date: 2026-07-09
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision = "0005_option_reference_tables"
down_revision = "0004_group_pet_tables"
branch_labels = None
depends_on = None

# 시드 (DATA_MODEL.md 10장 표 그대로)
CONDITION_SEED = [
    {"code": "diabetes", "label_ko": "당뇨", "dietary_tags": ["low_sugar", "low_gi"], "sort_order": 1, "is_active": True},
    {"code": "pregnancy", "label_ko": "임신 중", "dietary_tags": ["no_alcohol", "no_raw"], "sort_order": 2, "is_active": True},
    {"code": "ckd", "label_ko": "신장 질환", "dietary_tags": ["low_sodium", "low_potassium", "low_phosphorus"], "sort_order": 3, "is_active": True},
    {"code": "cancer", "label_ko": "암 치료 중", "dietary_tags": ["high_protein", "food_safety"], "sort_order": 4, "is_active": True},
    {"code": "hypertension", "label_ko": "고혈압", "dietary_tags": ["low_sodium"], "sort_order": 5, "is_active": True},
]

ALLERGEN_SEED = [
    {"code": "peanut", "label_ko": "땅콩", "exclude_keywords": ["땅콩", "피넛"], "sort_order": 1, "is_active": True},
    {"code": "milk", "label_ko": "우유", "exclude_keywords": ["우유", "유제품", "치즈", "버터", "크림"], "sort_order": 2, "is_active": True},
    {"code": "shellfish", "label_ko": "갑각류", "exclude_keywords": ["새우", "게", "랍스터", "갑각류"], "sort_order": 3, "is_active": True},
    {"code": "egg", "label_ko": "계란", "exclude_keywords": ["계란", "달걀", "마요네즈"], "sort_order": 4, "is_active": True},
    {"code": "wheat", "label_ko": "밀", "exclude_keywords": ["밀", "밀가루", "빵", "면", "파스타"], "sort_order": 5, "is_active": True},
    {"code": "soy", "label_ko": "대두", "exclude_keywords": ["대두", "콩", "두부", "간장", "된장"], "sort_order": 6, "is_active": True},
    {"code": "peach", "label_ko": "복숭아", "exclude_keywords": ["복숭아"], "sort_order": 7, "is_active": True},
]


def upgrade() -> None:
    condition_types = op.create_table(
        "condition_types",
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("label_ko", sa.String(length=50), nullable=False),
        # 추천 엔진 내부용 태그. 메타 API 로 노출하지 않는다.
        sa.Column("dietary_tags", JSONB(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )

    allergen_types = op.create_table(
        "allergen_types",
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("label_ko", sa.String(length=50), nullable=False),
        # 추천 엔진 내부용 제외 키워드. 메타 API 로 노출하지 않는다.
        sa.Column("exclude_keywords", JSONB(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )

    op.bulk_insert(condition_types, CONDITION_SEED)
    op.bulk_insert(allergen_types, ALLERGEN_SEED)

    # user_conditions.condition: 기존 값 5종이 코드와 동일하므로 변환 없이 FK 만 건다.
    op.create_foreign_key(
        "fk_user_conditions_condition_condition_types",
        "user_conditions",
        "condition_types",
        ["condition"],
        ["code"],
    )

    # user_allergies.allergen: 한국어 자유 문자열 → 표준 코드 변환 후 FK.
    user_allergies = sa.table("user_allergies", sa.column("allergen", sa.String))
    for row in ALLERGEN_SEED:
        op.execute(
            user_allergies.update()
            .where(user_allergies.c.allergen == row["label_ko"])
            .values(allergen=row["code"])
        )

    # 매핑 불가 행은 삭제한다 (DATA_MODEL.md 10장 확정).
    codes = [row["code"] for row in ALLERGEN_SEED]
    op.execute(user_allergies.delete().where(user_allergies.c.allergen.not_in(codes)))

    op.create_foreign_key(
        "fk_user_allergies_allergen_allergen_types",
        "user_allergies",
        "allergen_types",
        ["allergen"],
        ["code"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_user_allergies_allergen_allergen_types", "user_allergies", type_="foreignkey")
    op.drop_constraint("fk_user_conditions_condition_condition_types", "user_conditions", type_="foreignkey")

    # allergen 을 코드 → 한국어 라벨로 되돌린다 (0005 이전의 자유 문자열 의미).
    user_allergies = sa.table("user_allergies", sa.column("allergen", sa.String))
    for row in ALLERGEN_SEED:
        op.execute(
            user_allergies.update()
            .where(user_allergies.c.allergen == row["code"])
            .values(allergen=row["label_ko"])
        )

    op.drop_table("allergen_types")
    op.drop_table("condition_types")
