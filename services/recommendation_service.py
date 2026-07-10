import random
from datetime import date
from math import ceil

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.consent_model import UserAllergy, UserCondition
from models.health_model import FoodNutrition
from models.meta_model import AllergenType, ConditionType
from models.recommendation_model import DietRecommendation
from services import health_service

MAX_ITEMS = 3
# 12장 확정 범위(30~50) 안에서 고정.
CANDIDATE_POOL_SIZE = 40

# breakfast/lunch/dinner 는 가능하면 이 계열 1개를 포함한다 (13장 구성 다양성).
STAPLE_GROUPS = ("밥류", "죽 및 스프류")

# 임포트 후 SELECT DISTINCT food_group 실측(25종)으로 확정한 매핑 (DATA_MODEL.md 12장).
# 제외: 장류·양념류/장아찌·절임류/젓갈류(양념·소량 반찬), 원재료성 소수 그룹(수·조·어·육류 등).
_MEAL_GROUPS: tuple[str, ...] = (
    "밥류",
    "죽 및 스프류",
    "국 및 탕류",
    "찌개 및 전골류",
    "면 및 만두류",
    "구이류",
    "볶음류",
    "찜류",
    "조림류",
    "튀김류",
    "전·적 및 부침류",
    "생채·무침류",
    "나물·숙채류",
    "김치류",
)
_SNACK_GROUPS: tuple[str, ...] = (
    "빵 및 과자류",
    "음료 및 차류",
    "유제품류 및 빙과류",
    "과일류",
)
MEAL_FOOD_GROUPS: dict[str, tuple[str, ...]] = {
    "breakfast": _MEAL_GROUPS,
    "lunch": _MEAL_GROUPS,
    "dinner": _MEAL_GROUPS,
    "snack": _SNACK_GROUPS,
}

# 질병 dietary_tags → 오름차순 정렬 컬럼 (12장). 임계값 판정이 아니라 상대 우선순위다.
TAG_SORT_COLUMNS = {
    "low_sodium": FoodNutrition.sodium_mg,
    "low_sugar": FoodNutrition.sugar_g,
    "low_gi": FoodNutrition.sugar_g,
    "low_potassium": FoodNutrition.potassium_mg,
    "low_phosphorus": FoodNutrition.phosphorus_mg,
}

# reason 템플릿에 쓰는 태그별 문구 (13장 — LLM 문장 생성 없음).
TAG_REASON_PHRASES = {
    "low_sodium": "나트륨이 낮은",
    "low_sugar": "당류가 낮은",
    "low_gi": "당류가 낮은",
    "low_potassium": "칼륨이 낮은",
    "low_phosphorus": "인이 낮은",
}


def get_recommendation(
    db: Session,
    user_id: int,
    rec_date: date,
    meal_type: str,
) -> tuple[DietRecommendation, bool]:
    cached = db.scalar(
        select(DietRecommendation).where(
            DietRecommendation.user_id == user_id,
            DietRecommendation.rec_date == rec_date,
            DietRecommendation.meal_type == meal_type,
        )
    )
    if cached is not None:
        return cached, True

    # 남은 칼로리는 summary 와 동일 산식 (target_kcal - consumed, 목표 미설정이면 None).
    remaining_kcal = health_service.get_summary(db, user_id, rec_date)["remaining_kcal"]
    conditions = _user_condition_types(db, user_id)
    allergens = _user_allergen_types(db, user_id)

    excluded: list[dict] = [
        {"type": "condition", "code": row.code, "label": row.label_ko} for row in conditions
    ] + [
        {"type": "allergen", "code": row.code, "label": row.label_ko} for row in allergens
    ]

    # 후보도 선정도 식약처 실측 DB 규칙만 쓴다 — LLM 없음 (13장).
    pool = _candidate_pool(db, meal_type, remaining_kcal, conditions, allergens)
    candidates = _select_items(user_id, rec_date, meal_type, pool, conditions)
    items = _filter_by_exclude_keywords(candidates, allergens, excluded)

    recommendation = DietRecommendation(
        user_id=user_id,
        rec_date=rec_date,
        meal_type=meal_type,
        items=items,
        excluded=excluded,
        source="rule",
    )
    db.add(recommendation)
    db.commit()
    db.refresh(recommendation)
    return recommendation, False


def _user_condition_types(db: Session, user_id: int) -> list[ConditionType]:
    return list(
        db.scalars(
            select(ConditionType)
            .join(UserCondition, UserCondition.condition == ConditionType.code)
            .where(UserCondition.user_id == user_id)
            .order_by(ConditionType.sort_order.asc())
        ).all()
    )


def _user_allergen_types(db: Session, user_id: int) -> list[AllergenType]:
    return list(
        db.scalars(
            select(AllergenType)
            .join(UserAllergy, UserAllergy.allergen == AllergenType.code)
            .where(UserAllergy.user_id == user_id)
            .order_by(AllergenType.sort_order.asc())
        ).all()
    )


def _candidate_pool(
    db: Session,
    meal_type: str,
    remaining_kcal: int | None,
    conditions: list[ConditionType],
    allergens: list[AllergenType],
) -> list[FoodNutrition]:
    """대분류별 상위 쿼터로 후보 풀을 만든다 (합계는 12장 범위 30~50 이내).

    전역 단일 정렬이면 무가당 음료 396종이 snack 풀 40개를 독식해 13장의
    구성 다양성("차 3잔" 방지)이 불가능하다 (실측). 태그 정렬은 그룹 안에서 적용한다.
    """
    groups = MEAL_FOOD_GROUPS[meal_type]
    group_quota = ceil(CANDIDATE_POOL_SIZE / len(groups))

    filters = [
        FoodNutrition.source == "mfds",
        FoodNutrition.food_group.in_(groups),
    ]

    if remaining_kcal is not None:
        filters.append(FoodNutrition.kcal_per_serving <= remaining_kcal)

    # 알러지 키워드는 이름 매칭으로 사전 제거한다. 후처리 필터와 이중 방어 (12장).
    for allergen in allergens:
        for keyword in allergen.exclude_keywords:
            filters.append(FoodNutrition.food_label.not_like(f"%{keyword}%"))

    # 태그가 여럿이면 질병 sort_order 순서대로 순차 정렬 키가 된다. 실측 없는 행은 뒤로.
    seen_columns: set[str] = set()
    order_by = []
    for condition in conditions:
        for tag in condition.dietary_tags:
            column = TAG_SORT_COLUMNS.get(tag)
            if column is None or column.key in seen_columns:
                continue
            seen_columns.add(column.key)
            order_by.append(column.asc().nulls_last())
    # 시드 셔플 재현성을 위해 id 로 tie-break 한다 — 같은 데이터면 풀 순서가 항상 같다.
    order_by.append(FoodNutrition.id.asc())

    rank = (
        func.row_number()
        .over(partition_by=FoodNutrition.food_group, order_by=order_by)
        .label("group_rank")
    )
    ranked = select(FoodNutrition.id.label("food_id"), rank).where(*filters).subquery()

    query = (
        select(FoodNutrition)
        .join(ranked, FoodNutrition.id == ranked.c.food_id)
        .where(ranked.c.group_rank <= group_quota)
        # 그룹별 정렬 상위 순서로 묶어 반환한다 — _select_items 의 그룹 내 상위 절반 계산 근거.
        .order_by(FoodNutrition.food_group.asc(), ranked.c.group_rank.asc())
    )
    return list(db.scalars(query).all())


def _select_items(
    user_id: int,
    rec_date: date,
    meal_type: str,
    pool: list[FoodNutrition],
    conditions: list[ConditionType],
) -> list[dict]:
    if not pool:
        # 후보 풀이 비면 빈 items 를 그대로 저장한다 (11·13장).
        return []

    has_sort_tags = any(
        tag in TAG_SORT_COLUMNS for condition in conditions for tag in condition.dietary_tags
    )
    if has_sort_tags:
        # 질병 태그가 있으면 정렬 상위 절반에서만 뽑아 수치 우선순위를 유지한다 (13장).
        # 절반은 그룹 안에서 계산한다 — 전역 절반이면 특정 그룹이 사라져 구성 다양성이 깨진다.
        by_group: dict[str, list[FoodNutrition]] = {}
        for row in pool:  # pool 은 (food_group, 그룹 내 정렬 순위) 순서다.
            by_group.setdefault(row.food_group, []).append(row)
        selection_pool = [
            row
            for rows in by_group.values()
            for row in rows[: max(1, ceil(len(rows) / 2))]
        ]
    else:
        selection_pool = list(pool)

    # 같은 (user, 날짜, 끼니)는 캐시 없이도 같은 결과, 날이 바뀌면 다른 조합 (13장 재현성·다양성).
    rng = random.Random(f"{user_id}:{rec_date.isoformat()}:{meal_type}")
    shuffled = list(selection_pool)
    rng.shuffle(shuffled)

    picked: list[FoodNutrition] = []
    used_groups: set[str] = set()

    if meal_type != "snack":
        # 가능하면 밥·죽 계열 1개를 포함한다 (13장).
        staple = next((row for row in shuffled if row.food_group in STAPLE_GROUPS), None)
        if staple is not None:
            picked.append(staple)
            used_groups.add(staple.food_group)

    # food_group 비중복 우선 선택 — "차 3잔" 같은 구성을 막는다 (13장).
    for row in shuffled:
        if len(picked) == MAX_ITEMS:
            break
        if row in picked or row.food_group in used_groups:
            continue
        picked.append(row)
        used_groups.add(row.food_group)

    # 그룹 종류가 모자라면 중복을 허용해 채운다 (비중복은 "가능한 경우"만, 13장).
    for row in shuffled:
        if len(picked) == MAX_ITEMS:
            break
        if row in picked:
            continue
        picked.append(row)

    reason = _rule_reason(conditions)
    return [
        {"name": row.food_label, "kcal": row.kcal_per_serving, "reason": reason} for row in picked
    ]


def _rule_reason(conditions: list[ConditionType]) -> str:
    phrases: list[str] = []
    for condition in conditions:
        for tag in condition.dietary_tags:
            phrase = TAG_REASON_PHRASES.get(tag)
            if phrase is not None and phrase not in phrases:
                phrases.append(phrase)
    if phrases:
        return f"식약처 영양 DB에서 {'·'.join(phrases)} 순으로 고른 메뉴입니다."
    return "식약처 영양 DB에서 남은 칼로리에 맞춰 고른 메뉴입니다."


def _filter_by_exclude_keywords(
    candidates: list[dict],
    allergens: list[AllergenType],
    excluded: list[dict],
) -> list[dict]:
    # 후보 풀 사전 제거가 1차, 이 후처리가 최종 보장이다 (11·12장 이중 방어).
    items: list[dict] = []
    for candidate in candidates:
        matched_keyword = _match_exclude_keyword(candidate["name"], allergens)
        if matched_keyword is not None:
            excluded.append(
                {"type": "filtered", "name": candidate["name"], "matched_keyword": matched_keyword}
            )
            continue
        items.append({"name": candidate["name"], "kcal": candidate["kcal"], "reason": candidate["reason"]})
    return items


def _match_exclude_keyword(name: str, allergens: list[AllergenType]) -> str | None:
    for allergen in allergens:
        for keyword in allergen.exclude_keywords:
            if keyword in name:
                return keyword
    return None
