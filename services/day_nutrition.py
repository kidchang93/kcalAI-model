"""하루 질환 축 누적 — "오늘 나트륨 얼마나 먹었나"를 답한다.

경고(`nutrition_service.get_record_warnings`)는 **기록 확정 직전 그 순간**에만 보인다. 저장하고
나면 그 정보가 어디에도 남지 않아, 만성질환자에게 가장 중요한 숫자를 볼 화면이 없었다.
이 모듈이 그 공백을 메운다 — 같은 실측 데이터를 하루 단위로 합산한다.

**설계 원칙 세 가지**

1. **실측 조회는 경고와 같은 규약을 쓴다** (`nutrition_service.measured_nutrition_for`).
   두 곳이 다르게 찾으면 "경고는 떴는데 합계에는 안 잡히는" 음식이 생긴다.
2. **나트륨만 상한 대비이고 칼륨·인은 참고치다.** KDOQI 2020 은 칼륨·인을 혈청 수치 기반
   개인화로 두고 하루 mg 상한을 권고하지 않는다 (`ckd_food_rules` 하단 주석 · CKD_NUTRITION 3-6).
3. **못 센 항목 수를 숨기지 않는다.** 실측이 없는 음식(외국 요리·가공식품 일부)은 합계에서
   빠지므로 실제보다 적게 보인다. `measured_items`/`total_items` 를 함께 내려, 앱이 "5개 중
   3개 기준"이라고 밝힐 수 있게 한다. 이걸 감추면 커버리지 구멍이 "적게 먹었다"로 읽힌다
   (`PRODUCT_STRATEGY.md` §5-2 의 curated 결측 사건과 같은 종류의 실수).

**수치는 `meal_items` 에 굳어 있는 스냅샷을 읽는다** (리비전 0025). 예전에는 매 조회 시
food_label 로 실측 행을 다시 찾아 `serving_ratio` 를 곱했고, 그래서 DB 값이 보정되면 과거
합계도 따라 바뀌었다 — 2026-07-25에 1인분 기준 4,536행과 동명 행 규칙을 고치자 지난 기록이
말하는 나트륨이 실제로 달라졌다. 기록은 기록이어야 한다 (`docs/PRODUCT_STRATEGY.md` §0-1).

같은 스냅샷을 기간 단위로 합치는 것이 `get_period_nutrient_axes` 다 (리포트 탭).
"""

from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from timeutil import UTC
from models.health_model import MealItem, MealLog
from services import chronic_food_rules, ckd_food_rules, meta_service, nutrition_service

# 하루 누적 축 (tag, nutrient, label). **경고 축(`ckd_food_rules.WARNING_AXES`)과 같지 않다.**
#
# 2026-07-25에 경고에 당류 축을 추가하면서 이 목록이 그걸 그대로 참조하고 있던 탓에 당류가
# 하루 누적에도 딸려 들어갔고, 두 가지가 조용히 깨졌다 — 컬럼이 `sugar_g`(g)라 `{nutrient}_mg`
# 조회가 빗나가 **항상 0**이었고, 참고치 분기가 칼륨이 아니면 인으로 떨어져 **"당류 투석 시
# 참고치 하루 1,000 mg"**이라는 **존재하지 않는 기준**이 표시됐다.
#
# 당류를 여기 넣지 않는 이유는 버그 때문이 아니라 근거가 없어서다:
#   (1) 우리 DB 는 총당류이고 지침 대상은 첨가당이다 — 하루 총당류를 합하면 지침이 권장하는
#       사과·우유가 그대로 들어간다 (CHRONIC_NUTRITION_SOURCES.md §2-2).
#   (2) 간식·음료 행의 1인분이 제품 한 통이라 합계 자체가 틀린다 (§2-5).
#   (3) 첨가당의 1일 상한은 KDA2025 에 수치가 없다.
# 셋 중 하나라도 풀리기 전에는 하루 당류 합계를 보여주지 않는다. 경고(무엇을 먹었는지)와
# 누적(얼마나 먹었는지)은 **요구하는 근거의 수준이 다르다.**
_AXES: tuple[tuple[str, str, str], ...] = (
    ("low_sodium", "sodium", "나트륨"),
    ("low_potassium", "potassium", "칼륨"),
    ("low_phosphorus", "phosphorus", "인"),
)

# 축 → FoodNutrition 컬럼. `getattr(row, f"{nutrient}_mg")` 로 이름을 조립하면 축을 늘렸을 때
# 컬럼이 없어도 예외 없이 None 이 되어 **조용히 0으로 집계된다**(2026-07-25 실측). 명시적으로
# 적고, 모르는 축은 아래에서 예외로 만든다.
_AXIS_COLUMNS: dict[str, str] = {
    "sodium": "sodium_mg",
    "potassium": "potassium_mg",
    "phosphorus": "phosphorus_mg",
}

# 나트륨 1일 상한을 가진 질환 (병기와 무관하게 단일 값). CKD 는 병기별이라 여기 없다.
# (상한 mg, 질환 표시명, 출처). 출처는 기준선을 보일 때 같은 줄에 붙는다 — 누가 그은 선인지.
_SODIUM_LIMIT_BY_CONDITION: dict[str, tuple[int, str, str]] = {
    "hypertension": (
        chronic_food_rules.HTN_SODIUM_MG_PER_DAY,
        "고혈압",
        chronic_food_rules.HTN_SODIUM_CITATION,
    ),
    "diabetes": (
        chronic_food_rules.DM_SODIUM_MG_PER_DAY,
        "당뇨",
        chronic_food_rules.DM_SODIUM_CITATION,
    ),
}

# 하루 누적을 노출할 때 항상 함께 내리는 고지. 수치가 추정 기반이라는 사실과, 이것이 진료
# 기준이 아니라는 사실 두 가지를 말한다.
DAILY_NUTRIENT_NOTICE = (
    "표시되는 수치는 기록한 음식의 실측값을 먹은 양 기준으로 합한 추정치입니다. "
    "목표량은 병기·검사 결과에 따라 다르니 의료진·영양사와 상담하세요."
)


def get_day_nutrient_axes(db: Session, user_id: int, target_date: date) -> dict | None:
    """오늘 먹은 음식의 질환 축 누적. 해당 질환이 없으면 None (앱은 카드를 그리지 않는다)."""
    axes = _axes_for_user(db, user_id)

    if not axes:
        return None

    items = _day_items(db, user_id, target_date)
    stage = meta_service.get_user_ckd_stage(db, user_id)
    conditions = {condition.code for condition in meta_service.list_user_condition_types(db, user_id)}

    totals: dict[str, float] = {nutrient: 0.0 for nutrient in axes}
    measured_counts: dict[str, int] = {nutrient: 0 for nutrient in axes}

    for item in items:
        for nutrient in axes:
            # 모르는 축은 조용히 0이 되지 않고 여기서 터진다 — 축을 늘리면 컬럼 매핑도 함께
            # 늘리라는 뜻이고, 단위가 mg 가 아닌 축은 애초에 이 합계에 들어올 수 없다.
            value = getattr(item, _AXIS_COLUMNS[nutrient])

            if value is None:
                continue

            totals[nutrient] += float(value)
            measured_counts[nutrient] += 1

    payloads = [
        _axis_payload(nutrient, totals[nutrient], measured_counts[nutrient], conditions, stage)
        for nutrient in axes
    ]

    return {
        "axes": payloads,
        "total_items": len(items),
        "notice": _notice(payloads),
    }


def get_period_nutrient_axes(
    db: Session, user_id: int, start_date: date, end_date: date
) -> dict | None:
    """기간(주·월)의 질환 축 추이. 해당 질환이 없으면 None (리포트가 카드를 그리지 않는다).

    하루 누적(`get_day_nutrient_axes`)이 "오늘 얼마나"라면 이쪽은 **"요즘 어떤가"**다.
    만성질환 관리에서 하루는 흔들리고 추세가 말을 한다 — 검사 수치가 나빠졌을 때 되짚을 수
    있어야 한다는 목표 지표(`docs/PRODUCT_STRATEGY.md` §0-2)가 이 화면을 요구한다.

    수치는 `meal_items` 스냅샷이라 **과거가 흔들리지 않는다** (리비전 0025).

    평균은 **기록한 날만** 나눈다. 기록 없는 날을 0으로 넣어 평균을 내리면 "적게 먹었다"로
    읽히는데, 실제로는 기록을 안 한 것이다 (`measured_items` 를 숨기지 않는 것과 같은 이유).
    """
    axes = _axes_for_user(db, user_id)

    if not axes:
        return None

    stage = meta_service.get_user_ckd_stage(db, user_id)
    conditions = {condition.code for condition in meta_service.list_user_condition_types(db, user_id)}

    start, _ = _day_bounds(start_date)
    _, end = _day_bounds(end_date)
    day_column = func.date(func.timezone("UTC", MealLog.logged_at))

    columns = [func.sum(getattr(MealItem, _AXIS_COLUMNS[nutrient])) for nutrient in axes]
    counts = [func.count(getattr(MealItem, _AXIS_COLUMNS[nutrient])) for nutrient in axes]

    rows = db.execute(
        select(day_column.label("day"), func.count(MealItem.id), *columns, *counts)
        .join(MealLog, MealLog.id == MealItem.meal_log_id)
        .where(
            MealLog.user_id == user_id,
            MealLog.deleted_at.is_(None),
            MealLog.logged_at >= start,
            MealLog.logged_at < end,
        )
        .group_by(day_column)
    ).all()

    by_day = {row[0]: row for row in rows}
    axis_days: dict[str, list[dict]] = {nutrient: [] for nutrient in axes}
    total_days = (end_date - start_date).days + 1

    for offset in range(total_days):
        day = start_date + timedelta(days=offset)
        row = by_day.get(day)

        for index, nutrient in enumerate(axes):
            # row = (day, total_items, *sums, *counts)
            consumed = None if row is None else row[2 + index]
            measured = 0 if row is None else row[2 + len(axes) + index]
            axis_days[nutrient].append(
                {
                    "date": day.isoformat(),
                    "consumed_mg": round(float(consumed or 0), 1),
                    "measured_items": int(measured),
                    "total_items": 0 if row is None else int(row[1]),
                }
            )

    payloads = []
    for nutrient in axes:
        days = axis_days[nutrient]
        recorded = [d for d in days if d["total_items"] > 0]
        limit_mg, basis = _sodium_limit(conditions, stage) if nutrient == "sodium" else (None, None)
        reference_mg, reference_note = (
            _reference(nutrient, stage) if nutrient != "sodium" else (None, None)
        )

        payloads.append(
            {
                "nutrient": nutrient,
                "label": ckd_food_rules.NUTRIENT_LABELS[nutrient],
                "days": days,
                # 기록한 날만 나눈다 (docstring).
                "average_mg": (
                    round(sum(d["consumed_mg"] for d in recorded) / len(recorded), 1)
                    if recorded
                    else None
                ),
                "recorded_days": len(recorded),
                "limit_mg": limit_mg,
                # 상한이 있는 축(나트륨)만 셀 수 있다. 기록 없는 날은 넘었는지 알 수 없으므로 뺀다.
                "days_over_limit": (
                    len([d for d in recorded if d["consumed_mg"] > limit_mg])
                    if limit_mg is not None
                    else None
                ),
                "reference_mg": reference_mg,
                "basis": basis or reference_note,
            }
        )

    return {
        "axes": payloads,
        "notice": _notice(payloads),
    }


def _notice(payloads: list[dict]) -> str:
    """고지문. 참고치를 하나라도 노출하면 그것이 지침 권고가 아니라는 사실을 덧붙인다."""
    if any(payload["reference_mg"] is not None for payload in payloads):
        return f"{DAILY_NUTRIENT_NOTICE} {ckd_food_rules.POTASSIUM_PHOSPHORUS_REFERENCE_NOTICE}"

    return DAILY_NUTRIENT_NOTICE


def _axes_for_user(db: Session, user_id: int) -> list[str]:
    """이 사용자에게 보여줄 영양 축. 질환의 dietary_tags 로 정하되 나트륨만 예외를 둔다."""
    tags: set[str] = set()
    codes: set[str] = set()

    for condition in meta_service.list_user_condition_types(db, user_id):
        tags.update(condition.dietary_tags)
        codes.add(condition.code)

    axes = [nutrient for tag, nutrient, _label in _AXES if tag in tags]

    # 당뇨의 dietary_tags 는 low_sugar·low_gi 라 나트륨 축이 안 잡히지만, 나트륨 1일 상한은
    # 지침에 있다(KDA2025 권고 9 — 2,300 mg). 태그가 아니라 근거를 따른다.
    if "sodium" not in axes and codes & _SODIUM_LIMIT_BY_CONDITION.keys():
        axes.insert(0, "sodium")

    return axes


def _day_bounds(target_date: date) -> tuple[datetime, datetime]:
    """끼니 조회(`health_service`)와 **같은 UTC 자정 경계**. 여기가 어긋나면 홈의 합계와
    기록 목록이 서로 다른 하루를 보게 된다."""
    start = datetime.combine(target_date, time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


def _day_items(db: Session, user_id: int, target_date: date) -> list[MealItem]:
    """그날 기록한 항목들.

    **수치는 항목에 굳어 있는 스냅샷을 쓴다** (리비전 0025) — 예전에는 `food_label`로
    `food_nutrition`을 매번 다시 조회해 합쳤고, 그래서 DB 값이 바뀌면 과거 기록이 말하는
    수치도 소급해 바뀌었다. 기록은 기록이어야 한다 (`docs/PRODUCT_STRATEGY.md` §0-1).
    """
    start, end = _day_bounds(target_date)

    return list(
        db.scalars(
            select(MealItem)
            .join(MealLog, MealLog.id == MealItem.meal_log_id)
            .where(
                MealLog.user_id == user_id,
                MealLog.deleted_at.is_(None),
                MealLog.logged_at >= start,
                MealLog.logged_at < end,
            )
        ).all()
    )


def _axis_payload(
    nutrient: str,
    consumed_mg: float,
    measured_items: int,
    conditions: set[str],
    stage: str | None,
) -> dict:
    limit_mg, basis = _sodium_limit(conditions, stage) if nutrient == "sodium" else (None, None)
    reference_mg, reference_note = (
        _reference(nutrient, stage) if nutrient != "sodium" else (None, None)
    )

    return {
        "nutrient": nutrient,
        "label": ckd_food_rules.NUTRIENT_LABELS[nutrient],
        "consumed_mg": round(consumed_mg, 1),
        # 상한이 있으면 앱이 게이지를 그린다. 없으면 수치만 보여준다.
        "limit_mg": limit_mg,
        # 상한이 아니라 실무 참고치다. 게이지로 쓰지 않는다.
        "reference_mg": reference_mg,
        "basis": basis or reference_note,
        "measured_items": measured_items,
    }


def _sodium_limit(conditions: set[str], stage: str | None) -> tuple[int | None, str | None]:
    """나트륨 1일 상한 — 여러 질환이 겹치면 **더 엄격한 쪽**을 쓴다.

    CKD 는 병기가 있어야 값이 나온다(비투석 2,000 · 투석 3,000). 병기를 모르면서 다른 질환도
    없으면 상한 없이 안내 문구만 준다 — 임의로 한쪽을 고르면 투석 환자에게는 과잉 제한이고
    비투석 환자에게는 느슨하다.

    기준선 설명(basis)에는 **출처를 같은 줄에** 붙인다 — "신장 질환 투석 전(보존기) 기준 하루
    2,000 mg · 대한신장학회 … p101·105". 앱이 그은 선처럼 읽히면 우리가 판정하는 쪽이 된다
    (KCAL-15·16). 앱·리포트는 이 문자열을 그대로 쓴다.
    """
    candidates: list[tuple[int, str, str]] = [
        _SODIUM_LIMIT_BY_CONDITION[code] for code in sorted(conditions) if code in _SODIUM_LIMIT_BY_CONDITION
    ]

    if "ckd" in conditions:
        ckd_limit = ckd_food_rules.sodium_daily_limit_mg(stage)

        if ckd_limit is not None:
            candidates.append(
                (
                    ckd_limit,
                    f"신장 질환 {ckd_food_rules.CKD_STAGE_LABELS[stage]}",
                    ckd_food_rules.SODIUM_LIMIT_CITATIONS[stage],
                )
            )
        elif not candidates:
            return None, ckd_food_rules.SODIUM_STAGE_UNKNOWN_NOTE

    if not candidates:
        return None, None

    limit_mg, source, citation = min(candidates, key=lambda item: item[0])

    return limit_mg, f"{source} 기준 하루 {limit_mg:,} mg · {citation}"


def _reference(nutrient: str, stage: str | None) -> tuple[int | None, str | None]:
    """칼륨·인의 실무 참고치. **투석 중일 때만** 준다 — 비투석에 상시 제한은 근거가 없다.

    KSN1 서문: 초기 CKD 에 과도한 제한은 오히려 영양실조를 부른다.
    """
    on_dialysis = stage in (
        ckd_food_rules.CKD_STAGE_HEMODIALYSIS,
        ckd_food_rules.CKD_STAGE_PERITONEAL,
    )

    if not on_dialysis:
        return None, None

    # **아는 축에만 참고치를 준다.** 예전에는 "칼륨이 아니면 인"으로 갈라져, 새 축이 들어오자
    # 인의 투석 참고치가 그 축에 붙어 나갔다 — 당류에 "투석 시 참고치 하루 1,000 mg"이라는
    # 존재하지 않는 기준이 표시됐다(2026-07-25). 의학 수치는 기본값으로 흘려보내면 안 된다.
    reference_by_nutrient = {
        "potassium": ckd_food_rules.DIALYSIS_POTASSIUM_REFERENCE_MG,
        "phosphorus": ckd_food_rules.DIALYSIS_PHOSPHORUS_REFERENCE_MG,
    }
    reference_mg = reference_by_nutrient.get(nutrient)

    if reference_mg is None:
        return None, None

    return (
        reference_mg,
        f"투석 시 참고치 하루 {reference_mg:,} mg · {ckd_food_rules.REFERENCE_CITATIONS[nutrient]}",
    )
