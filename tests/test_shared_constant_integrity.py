"""여러 모듈이 나눠 쓰는 상수가 **서로 어긋나지 않는지**.

2026-07-25에 같은 종류의 사고가 세 번 났다. 전부 "한쪽만 고쳐도 아무도 안 터지고 조용히
틀리는" 구조였다:

1. 경고 축(`WARNING_AXES`)에 당류를 더했더니 그 목록을 그대로 참조하던 하루 누적이 함께
   깨졌다 — 합계는 늘 0이 됐고, 참고치 분기가 기본값으로 떨어져 **"당류 투석 시 참고치
   1,000 mg"**이라는 존재하지 않는 기준이 화면에 나갔다.
2. 당뇨의 `dietary_tags`에 `low_sodium`이 없어 **나트륨 축이 한 번도 돌지 않았다.** 등급
   계산 쪽은 당뇨를 포함하고 있었는데 태그만 비어 있었다.
3. 질병에 축이 붙으면 `exclude_keywords` 경로를 타지 않는데, 그 키워드를 축이 흡수하지
   않으면 그동안 나가던 경고가 사라진다.

셋 다 **예외 없이** 틀렸다는 게 핵심이다. 그래서 규약을 문서에만 적지 않고 여기서 깨뜨린다.
새 축·새 병기·새 질환을 더할 때 이 파일이 먼저 빨간불을 켠다.
"""

import pytest
from sqlalchemy import select

from models.meta_model import ConditionType
from models.health_model import FoodNutrition, MealItem
from services import chronic_food_rules, ckd_food_rules, day_nutrition, health_service


class TestCkdStageConstants:
    """병기를 추가하면 **라벨과 목표치를 함께** 늘려야 한다.

    라벨만 늘리면 그 병기에 나트륨 상한이 없어지고(조용히 "기준 없음"), 목표치만 늘리면
    화면에 표시할 이름이 없다.
    """

    def test_labels_and_targets_cover_the_same_stages(self):
        assert set(ckd_food_rules.CKD_STAGE_LABELS) == set(ckd_food_rules.STAGE_TARGETS)

    def test_every_stage_has_a_sodium_limit(self):
        """나트륨 상한은 병기별로 갈리는 값이라 하나라도 비면 그 사용자에게 기준이 없어진다."""
        for stage, target in ckd_food_rules.STAGE_TARGETS.items():
            assert target.get("sodium_mg_max"), f"{stage} 에 sodium_mg_max 가 없다"

    def test_dialysis_stages_are_recognized_by_reference_logic(self):
        """투석 병기가 늘면 참고치 분기(`_reference`)도 알아야 한다."""
        dialysis = {ckd_food_rules.CKD_STAGE_HEMODIALYSIS, ckd_food_rules.CKD_STAGE_PERITONEAL}

        for stage in dialysis:
            reference, note = day_nutrition._reference("potassium", stage)
            assert reference is not None and note is not None, f"{stage} 에 참고치가 없다"


class TestNutrientAxisConstants:
    """축 목록과 컬럼 매핑이 어긋나면 합계가 **조용히 0**이 된다 (사고 1)."""

    def test_daily_axes_all_have_column_mappings(self):
        for _tag, nutrient, _label in day_nutrition._AXES:
            assert nutrient in day_nutrition._AXIS_COLUMNS, f"{nutrient} 컬럼 매핑 누락"

    def test_daily_axis_columns_exist_on_the_model(self):
        for nutrient, column in day_nutrition._AXIS_COLUMNS.items():
            assert hasattr(FoodNutrition, column), f"{nutrient} → {column} 가 모델에 없다"

    def test_every_axis_has_a_display_label(self):
        for _tag, nutrient, _label in ckd_food_rules.WARNING_AXES:
            assert nutrient in ckd_food_rules.NUTRIENT_LABELS, f"{nutrient} 표시명 누락"

    def test_snapshot_columns_exist_on_both_models(self):
        """기록 스냅샷(리비전 0025)은 두 모델의 컬럼을 이어 붙인다 — 한쪽만 있으면 터진다."""
        for item_column, food_column in health_service._SNAPSHOT_COLUMNS:
            assert hasattr(MealItem, item_column), f"MealItem.{item_column} 없음"
            assert hasattr(FoodNutrition, food_column), f"FoodNutrition.{food_column} 없음"


class TestWarningAxisTagsExistInDatabase:
    """**축의 태그가 DB 에 하나도 없으면 그 축은 영원히 돌지 않는다** (사고 2).

    경고 판정은 사용자 질병의 `dietary_tags`와 겹치는 축만 검사한다. 그래서 코드에 축을
    선언해도 어떤 질병도 그 태그를 갖고 있지 않으면 **아무 일도 일어나지 않는다** —
    당뇨 나트륨이 정확히 그 상태로 배포돼 있었다.
    """

    def test_every_warning_axis_is_reachable(self, db):
        tags_in_db: set[str] = set()
        for row in db.scalars(select(ConditionType)).all():
            tags_in_db.update(row.dietary_tags)

        for tag, nutrient, _label in ckd_food_rules.WARNING_AXES:
            assert tag in tags_in_db, (
                f"'{tag}'({nutrient}) 축을 가진 질병이 하나도 없다 — 이 축은 돌지 않는다. "
                "condition_types 시드나 마이그레이션을 확인할 것."
            )

    def test_sodium_tier_conditions_actually_have_the_axis(self, db):
        """나트륨 **등급**을 매기기로 한 질환은 나트륨 **축**도 가져야 한다.

        등급 계산에만 넣고 태그를 빠뜨리면 축이 안 돌아 등급도 나가지 않는다.
        """
        rows = {
            row.code: set(row.dietary_tags)
            for row in db.scalars(select(ConditionType)).all()
        }

        for code in chronic_food_rules.SODIUM_TIER_CONDITIONS:
            assert code in rows, f"{code} 질환이 DB 에 없다"
            assert "low_sodium" in rows[code], (
                f"{code} 는 나트륨 등급 대상인데 dietary_tags 에 low_sodium 이 없다 — "
                "축이 돌지 않아 등급도 나가지 않는다."
            )


class TestExcludeKeywordsAreAbsorbed:
    """질병에 축이 붙으면 `exclude_keywords` 경로를 타지 않는다 (사고 3).

    그 키워드를 축 판정이 흡수하지 않으면 그동안 나가던 경고가 **조용히 사라진다.**
    """

    AXIS_MATCHERS = {
        "sodium": ckd_food_rules.sodium_caution,
        "potassium": ckd_food_rules.potassium_high_match,
        "phosphorus": ckd_food_rules.phosphorus_caution,
        "sugar": chronic_food_rules.added_sugar_caution,
    }

    def test_no_keyword_is_lost_when_a_condition_gets_axes(self, db):
        axes_by_tag = {tag: nutrient for tag, nutrient, _label in ckd_food_rules.WARNING_AXES}
        lost: list[tuple[str, str]] = []

        for row in db.scalars(select(ConditionType)).all():
            active = [axes_by_tag[tag] for tag in row.dietary_tags if tag in axes_by_tag]

            if not active:
                continue  # 축이 없으면 exclude_keywords 경로가 그대로 산다.

            for keyword in row.exclude_keywords:
                if not any(self.AXIS_MATCHERS[nutrient](keyword) for nutrient in active):
                    lost.append((row.code, keyword))

        assert not lost, (
            f"축에 흡수되지 않은 exclude_keywords: {lost} — "
            "이 키워드들의 경고가 조용히 사라진다."
        )
