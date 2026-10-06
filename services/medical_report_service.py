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

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from timeutil import UTC, today_kst
from models.health_model import MealLog
from services import (
    ckd_food_rules,
    consent_service,
    health_service,
    lab_panels,
    lab_service,
    meta_service,
    subscription_service,
    visit_service,
)

REPORT_NOTICE = (
    "이 기록은 사용자가 앱에 직접 남긴 식단과 식약처 식품영양성분 DB 의 실측값을 합한 "
    "추정치입니다. 의료기기가 아니며 진단·치료·예방에 사용할 수 없습니다. "
    "실제 섭취량·조리법에 따라 실제 값과 다를 수 있습니다."
)

# 동의 문구가 개정돼 **질환·검사를 싣지 못한** 리포트에만 붙인다. 진료 문서에서 질환이 조용히
# 빠지면 "질환 없음"으로 읽힌다 — 빠진 이유를 문서 안에 남긴다.
# 동의가 없거나 철회한 경우에는 붙이지 않는다: 입력이 막혀 있거나 철회 때 파기돼 **실을 데이터가
# 애초에 없다** — 빠진 것이 없는데 빠졌다고 쓰면 그것도 틀린 기록이다.
REPORT_OUTDATED_CONSENT_NOTICE = (
    "건강 정보 동의 내용이 바뀌어 다시 동의하기 전까지 질환·병기·검사 수치는 이 기록에 싣지 않았습니다."
)

# ---- 리포트 기간 (DATA_MODEL 32-5) — 서버가 정한다. 앱만 막으면 웹 인쇄로 샌다. ----

# 출시 전이라 기존 회원(운영자·관계자뿐)에게 30일을 남기는 예외를 두지 않는다(2026-10-06 사용자 결정).
FREE_REPORT_DAYS = 14
PLUS_REPORT_DAYS = 365
# 플러스 기본 기간 — 지난 진료가 없거나 상한보다 오래됐을 때.
PLUS_FALLBACK_DAYS = 90

COMPARE_PLUS_ONLY_MESSAGE = "지난 진료 구간과 나란히 보기는 플러스에서 쓸 수 있어요."


def resolve_report_range(
    db: Session,
    user_id: int,
    start_date: date | None,
    end_date: date | None,
    today: date,
) -> tuple[date, date, dict]:
    """리포트 기간을 정한다 → (시작, 끝, 응답의 `range`).

    요청 기간이 상한보다 길면 **시작일을 당겨 자른다** — 400 이 아니다. 무료 사용자는 오류가 아니라 2주
    리포트를 받아야 한다. 역순(끝 < 시작)은 자르지 않고 `get_trends` 의 400 에 맡긴다.
    """
    is_plus = subscription_service.get_user_plan(db, user_id).price_krw > 0
    max_days = PLUS_REPORT_DAYS if is_plus else FREE_REPORT_DAYS
    last_visit_on, _ = visit_service.recent_visit_dates(db, user_id, today)

    end = end_date or today
    default_start = _default_start(is_plus, max_days, last_visit_on, end)
    start = start_date or default_start
    clamped = (end - start).days + 1 > max_days

    if clamped:
        start = end - timedelta(days=max_days - 1)

    return start, end, {
        "plan": "plus" if is_plus else "free",
        "max_days": max_days,
        "last_visit_on": last_visit_on,
        "clamped": clamped,
        "default_start_date": default_start,
    }



def _default_start(is_plus: bool, max_days: int, last_visit_on: date | None, end: date) -> date:
    # 플러스 = 지난 진료일부터. 무료 = 상한만큼 최근 — 무료에 '지난 진료부터'를 주면 상한에 잘려 늘 같다.
    if (
        is_plus
        and last_visit_on is not None
        and last_visit_on <= end
        and (end - last_visit_on).days + 1 <= max_days
    ):
        return last_visit_on

    return end - timedelta(days=(PLUS_FALLBACK_DAYS if is_plus else max_days) - 1)


def build_report(
    db: Session,
    user_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    today: date | None = None,
) -> dict:
    """기간 리포트. 기간은 `resolve_report_range` 가 요금제로 자르고, 역순 검증은 `get_trends` 가 한다.

    **질환·병기·검사 수치·질환 축은 민감정보 동의가 ACTIVE 일 때만 싣는다** (DATA_MODEL 7장).
    라우트는 막지 않는다 — 동의하지 않은 사용자도 칼로리·끼니 기록은 진료에 가져갈 수 있어야 한다.
    """
    start_date, end_date, report_range = resolve_report_range(
        db, user_id, start_date, end_date, today or today_kst()
    )
    trends = health_service.get_trends(db, user_id, start_date, end_date, max_days=PLUS_REPORT_DAYS)

    consent_state = consent_service.get_consent_state(db, user_id)
    readable = consent_state is consent_service.ConsentState.ACTIVE

    recorded = [day for day in trends["days"] if day["meal_count"] > 0]

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        # 언제 뽑은 문서인지 — 진료실에서 최신본인지 판단하는 근거다.
        "generated_at": datetime.now(UTC).isoformat(),
        "conditions": (
            [condition.label_ko for condition in meta_service.list_user_condition_types(db, user_id)]
            if readable
            else []
        ),
        "ckd_stage_label": _stage_label(db, user_id) if readable else None,
        "kcal": {
            "target": trends["target_kcal"],
            # 기록한 날만 나눈다 — 기간 추이와 같은 규칙 (기록 없는 날은 0이 아니라 '모름'이다).
            "average": _kcal_average(recorded),
            "recorded_days": len(recorded),
            "total_days": len(trends["days"]),
        },
        # get_trends 도 동의를 보고 None 을 주지만, 리포트가 싣는 민감정보는 이 함수 안에서 한 번에
        # 판정이 보이게 둔다 — 한쪽 게이트가 빠져도 문서에 새지 않는다.
        "nutrients": trends["nutrients"] if readable else None,
        # 검사 수치 (리비전 0027, `docs/CARE_LOOP.md` §4). 식단 요약 옆에 결과 축을 나란히
        # 놓는 것이 이 리포트의 목적이다 — 그전까지는 "무엇을 먹었나"만 있고 "그래서 수치가
        # 어떻게 됐나"가 없어, 진료에서 되짚을 근거가 절반이었다.
        #
        # ⚠️ 기간 밖의 값도 **직전 1건은 싣는다**. 검사는 3개월에 한 번인데 리포트 기간은
        # 보통 그보다 짧아, 기간으로만 자르면 대부분의 리포트에서 검사란이 비어 버린다.
        "labs": _labs_for_report(db, user_id, start_date, end_date) if readable else [],
        "meals": _meals_in_range(db, user_id, start_date, end_date),
        "notice": _report_notice(consent_state),
        "range": report_range,
    }


def build_compare(db: Session, user_id: int, today: date | None = None) -> dict:
    """지난 진료 구간(직전 진료일 → 지난 진료일 전날)과 이번 구간(지난 진료일 → 오늘)을 같은 모양으로 (32-5).

    플러스 전용 — 무료면 PlanLimitError(402). **판정하지 않는다** — 좋아졌다·나빠졌다를 서버가 말하지 않는다.
    지난 진료가 하나뿐이면 previous 는 None(앱이 비교 표를 숨긴다), 하나도 없으면 이번 구간은 최근 90일이다.
    """
    today = today or today_kst()
    plan = subscription_service.get_user_plan(db, user_id)

    if plan.price_krw <= 0:
        raise subscription_service.PlanLimitError(
            COMPARE_PLUS_ONLY_MESSAGE,
            resource=subscription_service.RESOURCE_REPORT_COMPARE,
            plan_code=plan.code,
            limit=0,
        )

    last_visit_on, previous_visit_on = visit_service.recent_visit_dates(db, user_id, today)
    current_start = last_visit_on or today - timedelta(days=PLUS_FALLBACK_DAYS - 1)
    previous = None

    if last_visit_on is not None and previous_visit_on is not None and previous_visit_on < last_visit_on:
        previous = _interval(db, user_id, previous_visit_on, last_visit_on - timedelta(days=1))

    return {"current": _interval(db, user_id, current_start, today), "previous": previous}


def _interval(db: Session, user_id: int, start: date, end: date) -> dict:
    # 한 구간도 리포트 상한(365일)을 넘기지 않는다 — 1년 넘게 진료가 없었으면 최근 1년만 본다.
    start = max(start, end - timedelta(days=PLUS_REPORT_DAYS - 1))
    trends = health_service.get_trends(db, user_id, start, end, max_days=PLUS_REPORT_DAYS)
    recorded = [day for day in trends["days"] if day["meal_count"] > 0]
    # 질환 축은 get_trends 가 동의를 보고 None 을 준다 — 동의가 없으면 빈 목록이다.
    axes = trends["nutrients"]["axes"] if trends["nutrients"] else []

    return {
        "start_date": start,
        "end_date": end,
        "total_days": len(trends["days"]),
        "recorded_days": len(recorded),
        "kcal_daily_avg": _kcal_average(recorded),
        "nutrients": [
            {
                "nutrient": axis["nutrient"],
                "label": axis["label"],
                "unit": "mg",
                # 리포트와 같은 규칙 — 기록한 날만 나눈 평균.
                "daily_avg": axis["average_mg"],
                "measured_days": sum(1 for day in axis["days"] if day["measured_items"] > 0),
            }
            for axis in axes
        ],
    }


def _kcal_average(recorded_days: list[dict]) -> int | None:
    if not recorded_days:
        return None

    return round(sum(day["consumed_kcal"] for day in recorded_days) / len(recorded_days))


def _report_notice(consent_state: consent_service.ConsentState) -> str:
    if consent_state is consent_service.ConsentState.OUTDATED:
        return f"{REPORT_NOTICE} {REPORT_OUTDATED_CONSENT_NOTICE}"

    return REPORT_NOTICE


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
    meals = db.scalars(
        select(MealLog)
        .options(selectinload(MealLog.items))
        .where(*MealLog.live_between(user_id, start_date, end_date))
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
                    # Decimal 은 응답 스키마(`ReportMealItem`, float)가 변환한다.
                    "serving_ratio": item.serving_ratio,
                    "kcal": item.kcal,
                    # 기록 시점에 굳은 값 (리비전 0025). 실측이 없던 음식은 null 이고,
                    # 그 사실이 진료 문서에도 그대로 드러나야 한다.
                    "sodium_mg": item.sodium_mg,
                    "potassium_mg": item.potassium_mg,
                    "phosphorus_mg": item.phosphorus_mg,
                }
                for item in meal.items
            ],
        }
        for meal in meals
    ]
