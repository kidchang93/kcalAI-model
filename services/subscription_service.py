from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from models.group_model import Group, GroupMember, GroupPet
from models.pet_model import Pet
from models.subscription_model import Plan, UserSubscription, VisionUsageDaily
from timeutil import KST, UTC, today_kst

# 가입 시 요금제를 고르지 않으면 무료 플랜으로 시작한다.
DEFAULT_PLAN_CODE = "lite"

# user_subscriptions.status (24장). 구독 행의 해석은 이 모듈이 주인이라 여기서 정의하고,
# billing_service 가 import 해서 쓴다 (양쪽에 리터럴을 두면 조용히 어긋난다).
STATUS_ACTIVE = "active"
STATUS_CANCELED = "canceled"  # 자동갱신 해지 — 기간 만료까지는 유료 유지
STATUS_PAST_DUE = "past_due"  # 갱신 실패 — 유예 중

# 402 본문의 resource 값 — 앱이 어떤 업그레이드 화면을 띄울지 이걸로 분기한다.
RESOURCE_VISION_DAILY = "vision_daily"
RESOURCE_OWNED_GROUPS = "owned_groups"
RESOURCE_GROUP_MEMBERS = "group_members"
RESOURCE_PETS = "pets"


class PlanLimitError(Exception):
    """요금제 한도 초과. main.py 의 전역 핸들러가 402 로 변환한다.

    `ValueError` 를 상속하지 않는다 — 각 api 모듈의 `except ValueError → 400` 에 잡히면
    업그레이드 유도가 일반 입력 오류로 뭉개진다.
    """

    def __init__(self, message: str, *, resource: str, plan_code: str, limit: int) -> None:
        super().__init__(message)
        self.message = message
        self.resource = resource
        self.plan_code = plan_code
        self.limit = limit


# ---- 요금제 조회 ----

def list_plans(db: Session) -> list[Plan]:
    return list(
        db.scalars(
            select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order.asc())
        ).all()
    )


def get_plan(db: Session, plan_code: str) -> Plan:
    """기존 구독을 해석할 때 쓴다 — `is_active` 를 보지 않는다.

    `is_active` 는 "지금 **판매** 중인가"이지 "기존 구독을 인정하는가"가 아니다. 여기서
    활성 플랜만 반환하면, 요금제 하나를 판매 중단하는 순간 그 요금제를 쓰던 기존 회원 전원의
    요청이 ValueError 로 깨진다 (predict 는 500).
    """
    plan = db.scalar(select(Plan).where(Plan.code == plan_code))

    if plan is None:
        raise ValueError("존재하지 않는 요금제입니다.")

    return plan


def get_purchasable_plan(db: Session, plan_code: str) -> Plan:
    """새로 **선택**하는 경로(가입·변경)에서 쓴다 — 판매 중단된 플랜은 고를 수 없다."""
    plan = db.scalar(select(Plan).where(Plan.code == plan_code, Plan.is_active.is_(True)))

    if plan is None:
        raise ValueError("존재하지 않는 요금제입니다.")

    return plan


def get_subscription(
    db: Session, user_id: int, for_update: bool = False
) -> UserSubscription:
    """회원의 구독 행. 없으면 무료 플랜으로 만들어 준다.

    가입 시 항상 만들지만(`create_subscription`), 0014 이전에 가입한 회원이나 백필 누락에
    대비해 조회 경로에서도 자기치유한다 — 구독 행이 없다고 기능이 500 으로 죽으면 안 된다.

    `for_update=True` 면 구독 행에 행 잠금을 건다. 한도 판정(ensure_can_*)은 count-then-insert
    라 잠금 없이는 동시 요청이 둘 다 통과해 정원을 넘길 수 있다. 잠금은 **호출자의 commit 까지**
    유지되므로, 같은 소유자의 '추가'가 직렬화된다.
    """
    statement = select(UserSubscription).where(UserSubscription.user_id == user_id)

    if for_update:
        statement = statement.with_for_update()

    subscription = db.scalar(statement)

    if subscription is None:
        subscription = create_subscription(db, user_id, DEFAULT_PLAN_CODE)

        # 자기치유는 그 자체로 완결된 복구다 — 읽기 전용 경로(GET /me/subscription)에서도
        # 남아야 한다. commit 하지 않으면 세션 종료와 함께 롤백되어 매 요청 재삽입된다.
        # 단 for_update 경로에서는 커밋하면 방금 건 잠금이 풀리므로 호출자의 commit 에 맡긴다.
        if not for_update:
            db.commit()

    return subscription


def get_effective_plan(db: Session, subscription: UserSubscription) -> Plan:
    """구독 행을 **실효 요금제**로 해석한다 — 유료인데 기간이 지났으면 무료(lite)다.

    행을 바꾸지 않는 이유가 핵심이다. 만료 시점에 `plan_code` 를 lite 로 써 버리면 (1) 갱신
    배치가 무엇을 청구해야 할지 잃고, (2) "이 회원은 Pro 였다"는 이력이 사라지며, (3) 만료를
    감지한 첫 요청이 쓰기 트랜잭션을 여는 부작용이 생긴다. 그래서 저장은 사실 그대로 두고
    **읽을 때 해석**한다 — 만료 강등이 한 곳(여기)에만 있으면 비전 쿼터·그룹·펫 한도가 전부
    자동으로 만료를 존중한다.

    `current_period_end` 가 없는 유료 구독은 만료 개념이 없는 것으로 본다 — 결제 이전에
    부여된 구독(가입 시 plan_code 선택)이 여기 해당한다.
    """
    plan = get_plan(db, subscription.plan_code)

    if plan.price_krw <= 0 or subscription.current_period_end is None:
        return plan

    period_end = subscription.current_period_end
    # DB(timestamptz)는 tz-aware 를 주지만 수기·테스트 데이터의 naive 값을 UTC 로 간주한다.
    if period_end.tzinfo is None:
        period_end = period_end.replace(tzinfo=UTC)

    if period_end > datetime.now(UTC):
        return plan

    return get_plan(db, DEFAULT_PLAN_CODE)


def get_user_plan(db: Session, user_id: int, for_update: bool = False) -> Plan:
    return get_effective_plan(db, get_subscription(db, user_id, for_update))


def create_subscription(db: Session, user_id: int, plan_code: str | None) -> UserSubscription:
    """가입 시 구독 행 생성. **유료 플랜은 여기서 부여하지 않는다.**

    가입 요청의 `plan_code` 를 그대로 믿으면 **결제 없이 Premium 을 얻는 경로**가 된다
    (게다가 `current_period_end` 가 null 이라 만료 강등도 비켜간다). 유료를 골랐더라도
    **무료로 시작**하고, 업그레이드는 `/api/billing/*` 결제 흐름(실제 청구 성공)으로만 한다.

    400 으로 막지 않는 이유: 가입 자체가 실패하면 사용자가 서비스에 들어오지도 못한다.
    유료 선택은 '의사표시'로 받고, 결제는 가입 후 요금제 화면에서 잇는다.

    가입 트랜잭션 안에서도 불리므로 commit 하지 않는다 (호출자가 커밋한다).
    """
    # 없는 plan_code 는 여기서 ValueError → 400 (기존 계약 유지).
    plan = get_purchasable_plan(db, plan_code or DEFAULT_PLAN_CODE)

    if plan.price_krw > 0:
        plan = get_purchasable_plan(db, DEFAULT_PLAN_CODE)

    subscription = UserSubscription(user_id=user_id, plan_code=plan.code)
    db.add(subscription)
    db.flush()
    return subscription


def change_plan(db: Session, user_id: int, plan_code: str) -> UserSubscription:
    """요금제 변경 — **무료(lite)로의 다운그레이드만** 허용한다 (24장).

    유료 플랜으로의 변경은 여기서 막는다. 이 경로에는 결제 검증이 없어, 열어 두면 누구나
    Premium 으로 바꿀 수 있다. 업그레이드는 `POST /api/billing/confirm`(실제 청구)을 거친다.

    다운그레이드로 이미 보유한 그룹·펫이 새 한도를 넘더라도 기존 데이터는 건드리지 않는다
    (사용자가 만든 것을 서버가 말없이 지우지 않는다). 초과 상태에서는 '추가'만 막힌다.

    무료 전환은 **즉시** 적용되며 남은 유료 기간을 포기한다. 기간을 유지한 채 자동갱신만 끄려면
    `POST /api/billing/cancel` 을 쓴다 — 유료 구독자에게는 그쪽이 정답이다.
    """
    plan = get_purchasable_plan(db, plan_code)

    if plan.price_krw > 0:
        raise ValueError("결제를 통해 업그레이드해주세요.")

    subscription = get_subscription(db, user_id)
    subscription.plan_code = plan.code
    # 무료로 내려가면 청구 상태를 비운다 — 남겨 두면 갱신 배치가 이미 무료인 회원을 청구 대상으로
    # 집어 든다(next_billing_at 이 살아 있으므로).
    subscription.status = STATUS_ACTIVE
    subscription.current_period_end = None
    subscription.next_billing_at = None
    subscription.cancel_at_period_end = False
    db.commit()
    db.refresh(subscription)
    return subscription


# ---- 비전 LLM 일일 쿼터 ----

def get_vision_usage(db: Session, user_id: int, usage_date: date | None = None) -> int:
    used = db.scalar(
        select(VisionUsageDaily.used_count).where(
            VisionUsageDaily.user_id == user_id,
            VisionUsageDaily.usage_date == (usage_date or today_kst()),
        )
    )
    return int(used or 0)


def consume_vision_quota(db: Session, user_id: int) -> tuple[int, int, date]:
    """비전 호출 1건을 선차감한다. 한도를 넘으면 `PlanLimitError`.

    판정과 증가를 한 문장의 UPSERT 로 원자화한다 — 동시 요청이 각자 COUNT 를 읽고 둘 다
    통과하는 경합을 막는다. `WHERE used_count < limit` 이 거짓이면 갱신되는 행이 없어
    RETURNING 이 비고, 그것이 곧 한도 초과 신호다.

    반환: `(사용량, 한도, 차감한 날짜)`. **환불은 반드시 이 날짜로 해야 한다** — 자정을 걸친
    요청에서 환불 시점의 오늘을 다시 계산하면 엉뚱한 날의 카운터를 깎는다.
    """
    plan = get_user_plan(db, user_id)
    limit = plan.daily_vision_quota
    usage_date = today_kst()

    if limit < 1:
        raise PlanLimitError(
            _quota_message(plan),
            resource=RESOURCE_VISION_DAILY,
            plan_code=plan.code,
            limit=limit,
        )

    statement = (
        pg_insert(VisionUsageDaily)
        .values(user_id=user_id, usage_date=usage_date, used_count=1)
        .on_conflict_do_update(
            index_elements=[VisionUsageDaily.user_id, VisionUsageDaily.usage_date],
            set_={
                "used_count": VisionUsageDaily.used_count + 1,
                "updated_at": func.now(),
            },
            where=VisionUsageDaily.used_count < limit,
        )
        .returning(VisionUsageDaily.used_count)
    )
    used = db.scalar(statement)

    if used is None:
        db.rollback()
        raise PlanLimitError(
            _quota_message(plan),
            resource=RESOURCE_VISION_DAILY,
            plan_code=plan.code,
            limit=limit,
        )

    db.commit()
    return int(used), limit, usage_date


def refund_vision_quota(db: Session, user_id: int, usage_date: date) -> None:
    """선차감한 1건을 되돌린다 (인식 백엔드 장애 등 사용자 잘못이 아닌 실패).

    차감을 성공 후로 미루지 않는 이유는, 그러면 동시 요청이 전부 한도를 통과해 버리기
    때문이다. 먼저 잠그고, 실패하면 돌려준다.

    `usage_date` 는 **차감할 때 쓴 날짜**를 그대로 받는다. 여기서 today_kst() 를 다시 부르면,
    KST 자정을 걸친 요청(23:59 차감 → 00:00 실패)이 어제 깎은 것을 오늘 카운터에서 빼려 한다.
    """
    db.execute(
        update(VisionUsageDaily)
        .where(
            VisionUsageDaily.user_id == user_id,
            VisionUsageDaily.usage_date == usage_date,
            VisionUsageDaily.used_count > 0,
        )
        .values(used_count=VisionUsageDaily.used_count - 1, updated_at=func.now())
    )
    db.commit()


def next_vision_reset_at() -> datetime:
    # 다음 KST 자정. tz-aware 라 응답에서 UTC 로 직렬화된다.
    return datetime.combine(today_kst() + timedelta(days=1), time.min, tzinfo=KST)


# ---- 응답 조립 (api 레이어는 HTTP 변환만 한다) ----

def plan_view(plan: Plan) -> dict:
    return {
        "code": plan.code,
        "label": plan.label_ko,
        "price_krw": plan.price_krw,
        "daily_vision_quota": plan.daily_vision_quota,
        "max_group_members": plan.max_group_members,
        "max_pets": plan.max_pets,
        "max_owned_groups": plan.max_owned_groups,
    }


def list_plans_view(db: Session) -> dict:
    return {"plans": [plan_view(plan) for plan in list_plans(db)]}


def my_subscription_view(db: Session, user_id: int) -> dict:
    subscription = get_subscription(db, user_id)
    # 실효 플랜이다 — 만료된 유료 구독은 lite 로 보인다. 화면의 쿼터 표시가 402 판정과
    # 어긋나면 안 되므로, 여기서도 get_user_plan 과 같은 해석을 쓴다.
    plan = get_effective_plan(db, subscription)
    used = get_vision_usage(db, user_id)

    return {
        "plan": plan_view(plan),
        "vision_usage": {
            "used": used,
            "limit": plan.daily_vision_quota,
            "remaining": max(plan.daily_vision_quota - used, 0),
            "resets_at": next_vision_reset_at(),
        },
        "started_at": subscription.started_at,
        # 구독 상태(24장). 앱이 "해지 예약됨 · 7/31까지 이용 가능"을 그리려면 셋 다 필요하다.
        "status": subscription.status,
        "current_period_end": subscription.current_period_end,
        "next_billing_at": subscription.next_billing_at,
        "cancel_at_period_end": subscription.cancel_at_period_end,
    }


def _quota_message(plan: Plan) -> str:
    return (
        f"{plan.label_ko} 요금제는 하루 {plan.daily_vision_quota}건까지 사진 인식을 사용할 수 있습니다. "
        "내일 다시 시도하거나 요금제를 업그레이드해주세요."
    )


# ---- 그룹·반려동물 한도 ----
# 그룹 자원의 한도는 언제나 **그룹 소유자(owner)의 요금제**로 판정한다. 참여자가 무료 회원이어도
# 소유자가 결제한 정원 안에서는 들어올 수 있다 — 정원을 산 사람은 소유자다.

def ensure_can_create_group(db: Session, owner_id: int) -> None:
    plan = get_user_plan(db, owner_id, for_update=True)
    owned = int(
        db.scalar(select(func.count()).select_from(Group).where(Group.owner_id == owner_id))
    )

    if owned >= plan.max_owned_groups:
        raise PlanLimitError(
            f"{plan.label_ko} 요금제는 그룹을 {plan.max_owned_groups}개까지 만들 수 있습니다. "
            "요금제를 업그레이드해주세요.",
            resource=RESOURCE_OWNED_GROUPS,
            plan_code=plan.code,
            limit=plan.max_owned_groups,
        )


def ensure_can_add_member(db: Session, group: Group) -> None:
    plan = get_user_plan(db, group.owner_id, for_update=True)
    member_count = int(
        db.scalar(
            select(func.count()).select_from(GroupMember).where(GroupMember.group_id == group.id)
        )
    )
    # 한도는 "본인(owner) 제외 추가 인원"이다. 정원 = max_group_members + 1.
    added = max(member_count - 1, 0)

    if added >= plan.max_group_members:
        raise PlanLimitError(
            f"이 그룹은 {plan.label_ko} 요금제라 본인 외 {plan.max_group_members}명까지 참여할 수 있습니다. "
            "그룹 소유자가 요금제를 업그레이드해야 합니다.",
            resource=RESOURCE_GROUP_MEMBERS,
            plan_code=plan.code,
            limit=plan.max_group_members,
        )


def ensure_can_create_pet(db: Session, owner_id: int) -> None:
    plan = get_user_plan(db, owner_id, for_update=True)
    owned = int(
        db.scalar(
            select(func.count())
            .select_from(Pet)
            .where(Pet.owner_id == owner_id, Pet.deleted_at.is_(None))
        )
    )

    if owned >= plan.max_pets:
        raise PlanLimitError(
            f"{plan.label_ko} 요금제는 반려동물을 {plan.max_pets}마리까지 등록할 수 있습니다. "
            "요금제를 업그레이드해주세요.",
            resource=RESOURCE_PETS,
            plan_code=plan.code,
            limit=plan.max_pets,
        )


def ensure_can_attach_pet(db: Session, group: Group) -> None:
    plan = get_user_plan(db, group.owner_id, for_update=True)
    attached = int(
        db.scalar(
            select(func.count()).select_from(GroupPet).where(GroupPet.group_id == group.id)
        )
    )

    if attached >= plan.max_pets:
        raise PlanLimitError(
            f"이 그룹은 {plan.label_ko} 요금제라 반려동물을 {plan.max_pets}마리까지 참여시킬 수 있습니다. "
            "그룹 소유자가 요금제를 업그레이드해야 합니다.",
            resource=RESOURCE_PETS,
            plan_code=plan.code,
            limit=plan.max_pets,
        )
