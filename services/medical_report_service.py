"""진료·영양상담 지참용 기간 리포트.

## 왜 있는가

`docs/PRODUCT_STRATEGY.md` §0-2의 첫 번째 목표 지표는 **"진료·영양상담에서 실제로 열어
보였는가"**다. 그런데 그것을 가능하게 하는 기능이 하나도 없어 지표가 "미측정"으로 남아 있었다.

이 앱은 판단을 대신 내리지 않는다(§0-1). 대신 **판단할 사람에게 근거를 건넨다** — 여기서
판단할 사람에는 의료진·영양사가 포함된다. 환자가 "요즘 짜게 먹었나요?"라는 질문에
기억이 아니라 기록으로 답할 수 있게 하는 것이 이 API의 목적이다.

## 무엇을 담는가

- **누가**: 등록한 질환과 병기 (기준선이 거기서 갈리므로 수치보다 먼저 온다)
- **얼마나**: 질환 축별 일별 수치·기록일 평균·상한 초과일수 (`day_nutrition`과 같은 규칙)
- **무엇을**: 기간 내 끼니와 항목, 그리고 **그때 굳은 영양 스냅샷**(리비전 0025)
- **한계**: 실측을 못 찾은 항목 수와 고지문. 이걸 빼면 과소평가가 "적게 먹었다"로 읽힌다

수치는 전부 `meal_items` 스냅샷이라 **나중에 DB 를 고쳐도 이 문서는 바뀌지 않는다.** 진료
기록으로 쓰이려면 그래야 한다.
"""

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from timeutil import UTC
from models.health_model import MealLog
from services import (
    ckd_food_rules,
    day_nutrition,
    health_service,
    lab_panels,
    lab_service,
    meta_service,
)

# 진료 목적이라 상한을 추이(92일)와 같게 둔다 — 분기 단위 진료를 커버한다.
REPORT_MAX_DAYS = health_service.TRENDS_MAX_DAYS

REPORT_NOTICE = (
    "이 기록은 사용자가 앱에 직접 남긴 식단과 식약처 식품영양성분 DB 의 실측값을 합한 "
    "추정치입니다. 의료기기가 아니며 진단·치료·예방에 사용할 수 없습니다. "
    "실제 섭취량·조리법에 따라 실제 값과 다를 수 있습니다."
)


def build_report(db: Session, user_id: int, start_date: date, end_date: date) -> dict:
    """기간 리포트. 범위 검증은 추이와 같은 규칙을 쓴다."""
    if end_date < start_date:
        raise ValueError("종료일이 시작일보다 빠릅니다. 날짜 범위를 확인해주세요.")

    if (end_date - start_date).days + 1 > REPORT_MAX_DAYS:
        raise ValueError(f"조회 범위는 최대 {REPORT_MAX_DAYS}일입니다. 범위를 줄여 다시 시도해주세요.")

    trends = health_service.get_trends(db, user_id, start_date, end_date)
    recorded = [day for day in trends["days"] if day["meal_count"] > 0]

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        # 언제 뽑은 문서인지 — 진료실에서 최신본인지 판단하는 근거다.
        "generated_at": datetime.now(UTC).isoformat(),
        "conditions": [
            condition.label_ko for condition in meta_service.list_user_condition_types(db, user_id)
        ],
        "ckd_stage_label": _stage_label(db, user_id),
        "kcal": {
            "target": trends["target_kcal"],
            # 기록한 날만 나눈다 — 기간 추이와 같은 규칙 (기록 없는 날은 0이 아니라 '모름'이다).
            "average": (
                round(sum(day["consumed_kcal"] for day in recorded) / len(recorded))
                if recorded
                else None
            ),
            "recorded_days": len(recorded),
            "total_days": len(trends["days"]),
        },
        "nutrients": trends["nutrients"],
        # 검사 수치 (리비전 0027, `docs/CARE_LOOP.md` §4). 식단 요약 옆에 결과 축을 나란히
        # 놓는 것이 이 리포트의 목적이다 — 그전까지는 "무엇을 먹었나"만 있고 "그래서 수치가
        # 어떻게 됐나"가 없어, 진료에서 되짚을 근거가 절반이었다.
        #
        # ⚠️ 기간 밖의 값도 **직전 1건은 싣는다**. 검사는 3개월에 한 번인데 리포트 기간은
        # 보통 그보다 짧아, 기간으로만 자르면 대부분의 리포트에서 검사란이 비어 버린다.
        "labs": _labs_for_report(db, user_id, start_date, end_date),
        "meals": _meals_in_range(db, user_id, start_date, end_date),
        "notice": REPORT_NOTICE,
    }


def _labs_for_report(db: Session, user_id: int, start_date: date, end_date: date) -> list[dict]:
    """기간 안의 검사 + 항목별 직전 1건.

    검사 주기(3개월)가 리포트 기간보다 길다는 것이 이 함수가 존재하는 이유다. 기간으로만
    자르면 "이번 달 리포트"에는 검사값이 하나도 안 실린다 — 진료에서 가장 보고 싶은 것이
    지난번 수치인데도.
    """
    in_range = lab_service.list_results(db, user_id, start_date=start_date, end_date=end_date)
    covered = {row.panel for row in in_range}
    rows = list(in_range)

    # 기간에 없는 항목만 직전 값을 채운다. list_results 는 최신순이라 첫 행이 직전 값이다.
    for previous in lab_service.list_results(db, user_id, end_date=start_date):
        if previous.panel not in covered:
            covered.add(previous.panel)
            rows.append(previous)

    rows.sort(key=lambda row: (row.measured_on, row.panel), reverse=True)

    return [
        {
            "measured_on": row.measured_on.isoformat(),
            "panel": row.panel,
            # 표시명·정상범위를 서버가 싣는다 — 리포트는 인쇄되어 진료실에서 읽히는 문서라
            # 앱이 의학 용어를 만들면 안 된다.
            "label": (panel.label if (panel := lab_panels.get_panel(row.panel)) else row.panel),
            "value": float(row.value),
            "unit": row.unit,
            "reference": panel.reference if panel else None,
            "note": row.note,
            # 리포트 기간 밖의 값인지. 화면이 "기간 이전 검사"임을 밝힐 수 있어야 한다.
            "is_before_period": row.measured_on < start_date,
        }
        for row in rows
    ]


def _stage_label(db: Session, user_id: int) -> str | None:
    """신장병 병기 표시명. 미입력이면 None — 상한이 갈리는 값이라 진료 문서에 밝힌다.

    `consent_service.get_health_profile`을 쓰지 않는다 — 그쪽은 프로필이 없으면 **예외**를
    던져(혈액형 등록을 요구한다) 리포트 전체가 실패한다. 병기는 없어도 되는 값이다.
    """
    stage = meta_service.get_user_ckd_stage(db, user_id)

    return None if stage is None else ckd_food_rules.CKD_STAGE_LABELS.get(stage)


def _meals_in_range(db: Session, user_id: int, start_date: date, end_date: date) -> list[dict]:
    """기간 내 끼니와 항목. 정렬은 목록 API 와 같은 `logged_at` → `id` 다."""
    start, _ = day_nutrition._day_bounds(start_date)
    _, end = day_nutrition._day_bounds(end_date)

    meals = db.scalars(
        select(MealLog)
        .options(selectinload(MealLog.items))
        .where(
            MealLog.user_id == user_id,
            MealLog.deleted_at.is_(None),
            MealLog.logged_at >= start,
            MealLog.logged_at < end,
        )
        .order_by(MealLog.logged_at.asc(), MealLog.id.asc())
    ).all()

    return [
        {
            "date": meal.logged_at.astimezone(UTC).date().isoformat(),
            "logged_at": meal.logged_at.isoformat(),
            "meal_type": meal.meal_type,
            "total_kcal": meal.total_kcal,
            "items": [
                {
                    "food_label": item.food_label,
                    "serving_ratio": float(item.serving_ratio),
                    "kcal": item.kcal,
                    # 기록 시점에 굳은 값 (리비전 0025). 실측이 없던 음식은 null 이고,
                    # 그 사실이 진료 문서에도 그대로 드러나야 한다.
                    "sodium_mg": _as_float(item.sodium_mg),
                    "potassium_mg": _as_float(item.potassium_mg),
                    "phosphorus_mg": _as_float(item.phosphorus_mg),
                }
                for item in meal.items
            ],
        }
        for meal in meals
    ]


def _as_float(value) -> float | None:
    return None if value is None else float(value)
