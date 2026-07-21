"""주간 조언 — 기록을 근거로 한 규칙 기반 안내 (docs/ACTIVITY_GUIDANCE.md 3-5).

**LLM으로 문장을 생성하지 않는다.** `estimate` 조회에 LLM을 넣지 않는 것과 같은 이유다 —
같은 상황에 매번 다른 조언이 나오면 신뢰할 수 없고, 건강 조언은 재현성이 특히 중요하다.
모든 문구는 코드에 있고, 각 조언은 **근거 수치**를 함께 준다.

⚠️ 질병이 있으면 **강도·종목을 제시하지 않는다.** 신장병·고혈압·당뇨·임신은 운동 처방이 개별화
영역이고 투석 환자·임신부는 별도 지침이 있다. 이 경우 권장 범위와 함께 의료진 상담을 안내한다.
그래서 이 라우트는 질병을 읽고, **sensitive_health 동의가 필수**다.
"""

from datetime import date, timedelta

from sqlalchemy.orm import Session

from services import exercise_service, fitness_rules, health_service, meta_service

# 체중 추세를 보는 창. 짧으면 일상 변동(수분·식사)에 휘둘린다.
WEIGHT_TREND_DAYS = 28
# 이 정도는 움직여야 '추세'로 본다 (kg). 그보다 작으면 변동으로 취급한다.
WEIGHT_TREND_MIN_KG = 1.0
# 섭취가 목표에서 이만큼(%) 벗어나면 언급한다.
INTAKE_DEVIATION_RATIO = 0.2
# 조언은 많을수록 안 읽힌다. 우선순위 높은 것만 남긴다.
MAX_ADVICE = 4


def _condition_labels(db: Session, user_id: int) -> list[str]:
    return [row.label_ko for row in meta_service.list_user_condition_types(db, user_id)]


def _advice(code: str, tone: str, message: str, evidence: str | None = None) -> dict:
    # tone: good(잘하고 있음) · tip(제안) · caution(주의). 앱이 색과 아이콘을 고르는 축이다.
    return {"code": code, "tone": tone, "message": message, "evidence": evidence}


def _activity_advice(summary: dict, has_condition: bool) -> list[dict]:
    items: list[dict] = []
    remaining = summary["remaining_minutes"]
    target = summary["target_minutes"]

    if summary["achieved"]:
        items.append(
            _advice(
                "activity_achieved",
                "good",
                "이번 주 활동 목표를 채웠어요. 지금 리듬을 유지해보세요.",
                f"{summary['equivalent_moderate_minutes']}분 / 목표 {target}분",
            )
        )
    elif summary["exercise_count"] == 0:
        items.append(
            _advice(
                "activity_none",
                "tip",
                "이번 주 기록된 운동이 없어요. 가벼운 걷기부터 시작해보세요.",
                f"목표 {target}분",
            )
        )
    else:
        # 남은 분을 '하루 몇 분'으로 환산해 준다 — 총량보다 실행 가능한 단위가 낫다.
        per_day = max(1, round(remaining / 7))
        items.append(
            _advice(
                "activity_short",
                "tip",
                f"목표까지 {remaining}분 남았어요. 하루 {per_day}분씩이면 채울 수 있어요.",
                f"{summary['equivalent_moderate_minutes']}분 / 목표 {target}분",
            )
        )

    # 근력은 분이 아니라 일수 권고라 따로 본다.
    if summary["strength_days"] < summary["target_strength_days"]:
        items.append(
            _advice(
                "strength_short",
                "tip",
                "근력운동은 주 2일 이상이 권장돼요. 맨몸 운동도 괜찮아요."
                if not has_condition
                else "근력운동은 주 2일 이상이 권장돼요. 어떤 운동이 맞을지는 의료진과 상의하세요.",
                f"이번 주 {summary['strength_days']}일 / 권장 {summary['target_strength_days']}일",
            )
        )

    if summary["streak_weeks"] >= 2:
        items.append(
            _advice(
                "streak",
                "good",
                f"{summary['streak_weeks']}주 연속으로 목표를 채우고 있어요.",
                f"{summary['streak_weeks']}주 연속",
            )
        )

    return items


def _weight_advice(db: Session, user_id: int, today: date) -> list[dict]:
    logs = health_service.list_weights(db, user_id)
    window_start = today - timedelta(days=WEIGHT_TREND_DAYS)

    recent = [log for log in logs if log.measured_at.date() >= window_start]
    if len(recent) < 2:
        return []

    recent.sort(key=lambda log: log.measured_at)
    delta = float(recent[-1].weight_kg) - float(recent[0].weight_kg)

    if abs(delta) < WEIGHT_TREND_MIN_KG:
        return []

    goal = health_service.get_open_goal(db, user_id)
    goal_type = goal.goal_type if goal is not None else None
    direction = "늘었어요" if delta > 0 else "줄었어요"
    evidence = f"최근 {WEIGHT_TREND_DAYS}일 {delta:+.1f}kg"

    # 목표와 반대 방향으로 움직이면 목표 재설정을 **제안**한다(강요하지 않는다).
    if (goal_type == "loss" and delta > 0) or (goal_type == "gain" and delta < 0):
        return [
            _advice(
                "weight_against_goal",
                "caution",
                f"체중이 목표와 반대 방향으로 {direction}. 목표나 식단을 다시 살펴보는 건 어때요?",
                evidence,
            )
        ]

    if (goal_type == "loss" and delta < 0) or (goal_type == "gain" and delta > 0):
        return [_advice("weight_on_track", "good", f"체중이 목표 방향으로 {direction}.", evidence)]

    return [_advice("weight_changed", "tip", f"최근 체중이 {direction}.", evidence)]


def _intake_advice(db: Session, user_id: int, today: date) -> list[dict]:
    """최근 7일 평균 섭취를 목표와 비교한다. 하루치는 변동이 커서 보지 않는다."""
    start = today - timedelta(days=6)
    trends = health_service.get_trends(db, user_id, start, today)

    target = trends["target_kcal"]
    if target is None or target <= 0:
        return []

    logged_days = [day for day in trends["days"] if day["meal_count"] > 0]
    # 기록이 절반도 안 되는 주는 평균이 의미 없다 — 조언하지 않는다.
    if len(logged_days) < 4:
        return []

    average = round(sum(day["consumed_kcal"] for day in logged_days) / len(logged_days))
    deviation = (average - target) / target
    evidence = f"최근 {len(logged_days)}일 평균 {average:,}kcal / 목표 {target:,}kcal"

    if deviation > INTAKE_DEVIATION_RATIO:
        return [
            _advice("intake_over", "caution", "최근 섭취가 목표보다 꾸준히 많아요.", evidence)
        ]

    if deviation < -INTAKE_DEVIATION_RATIO:
        return [
            _advice(
                "intake_under",
                "caution",
                "최근 섭취가 목표보다 꾸준히 적어요. 너무 적게 먹고 있지는 않은지 살펴보세요.",
                evidence,
            )
        ]

    return [_advice("intake_on_track", "good", "최근 섭취가 목표 범위 안에 있어요.", evidence)]


def get_weekly_coaching(db: Session, user_id: int, today: date) -> dict:
    """이번 주 조언. 규칙 기반이라 같은 상황이면 같은 답이 나온다."""
    week_start, week_end = exercise_service.week_bounds(today)
    activity = exercise_service.get_summary(db, user_id, week_start, week_end)

    conditions = _condition_labels(db, user_id)
    has_condition = bool(conditions)

    items = (
        _activity_advice(activity, has_condition)
        + _weight_advice(db, user_id, today)
        + _intake_advice(db, user_id, today)
    )

    # caution → tip → good 순으로 보여준다. 사용자가 먼저 볼 것을 위로 올린다.
    tone_order = {"caution": 0, "tip": 1, "good": 2}
    items.sort(key=lambda item: tone_order.get(item["tone"], 3))

    return {
        "week_start": week_start,
        "week_end": week_end,
        "conditions": conditions,
        "items": items[:MAX_ADVICE],
        # 질병이 있으면 강도·종목 제시를 피하고 상담을 안내한다 (docs/ACTIVITY_GUIDANCE.md 3-5).
        "notice": fitness_rules.ACTIVITY_NOTICE,
    }
