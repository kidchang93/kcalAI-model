"""자동결제(토스 빌링) — 카드 등록·최초 청구·해지·갱신 배치 (DATA_MODEL.md 24장).

규약 네 가지가 이 모듈의 전부다.

1. **금액은 언제나 서버가 정한다** (`plans.price_krw`). 클라이언트가 보낸 금액은 받지도 않는다 —
   받으면 100원짜리 Premium 이 팔린다.
2. **원장(`payments`)이 먼저다.** 청구 전에 `ready` 행을 커밋해 두고, 결과로 `done`/`failed` 를
   덮는다. 외부 HTTP 중에 프로세스가 죽어도 "청구를 시도했다"는 사실이 남는다.
3. **이미 `done` 인 주문은 다시 반영하지 않는다** (`order_id` UNIQUE + `_mark_payment_done`).
   단 이 둘은 **갱신 배치의 방어선**이다 — 주문번호가 같아야 걸리기 때문이다.
4. **이미 낸 기간에 다시 청구하지 않는다** (`_is_duplicate_confirm`). confirm 은 호출마다 새
   `order_id` 를 만들어 3번이 걸리지 않으므로, 중복은 **구독 상태**로 판정한다.

빌링키는 `crypto.EncryptedString` 으로 암호화 저장되며(`BillingKey.billing_key`), 청구 직전에만
복호화해 쓴다. 로그·응답에 실어 나르지 않는다.
"""

import logging
import uuid
from calendar import monthrange
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from log_utils import setup_level_logger
from models.subscription_model import BillingKey, Payment, Plan, UserSubscription
from services import toss_client
from services.subscription_service import (
    STATUS_ACTIVE,
    STATUS_CANCELED,
    STATUS_PAST_DUE,
    get_plan,
    get_purchasable_plan,
    get_subscription,
)
from services.toss_client import TossError
from timeutil import UTC

info_logger = setup_level_logger(logging.INFO)
error_logger = setup_level_logger(logging.ERROR)

# user_subscriptions.status 는 subscription_service 가 정의한다 (위 import).
# payments.status
PAYMENT_READY = "ready"
PAYMENT_DONE = "done"
PAYMENT_FAILED = "failed"

# 갱신 실패 시 재시도 간격과, 재시도를 포기하는 기준(청구 예정일 = current_period_end 로부터).
# 무한 재시도를 두지 않는 이유: 만료된 카드는 영원히 실패하는데, 기간이 지나면 이미 lite 로
# 강등되므로(get_effective_plan) 결제사만 매일 두드리게 된다.
BILLING_RETRY_INTERVAL_DAYS = 1
BILLING_RETRY_MAX_DAYS = 3


# ---- 달력 인식 1개월 더하기 ----

def add_one_month(moment: datetime) -> datetime:
    """1개월 뒤. 말일은 클램프한다 — 1/31 + 1개월 = 2/28(윤년 2/29).

    `timedelta(days=30)` 을 쓰지 않는 이유는 결제 기념일이 매달 밀리기 때문이다(30일씩 12번이면
    5일이 어긋난다). 외부 의존(dateutil)을 들이지 않으려고 stdlib 로 직접 계산한다.
    """
    year = moment.year + (1 if moment.month == 12 else 0)
    month = 1 if moment.month == 12 else moment.month + 1
    day = min(moment.day, monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def _next_period_end(base: datetime, now: datetime) -> datetime:
    """`base` 기준 1개월 뒤. 이미 지난 시각이면 미래가 될 때까지 민다.

    기념일(base = 기존 기간 종료일)을 유지하되, 배치가 오래 멈췄다 돌아온 경우에도 다음 청구가
    과거로 잡혀 매 실행마다 재청구되는 루프를 만들지 않는다.
    """
    period_end = add_one_month(_as_utc(base))

    while period_end <= now:
        period_end = add_one_month(period_end)

    return period_end


def _as_utc(moment: datetime) -> datetime:
    # DB(timestamptz)는 tz-aware 를 주지만, 테스트·수기 데이터의 naive 값을 UTC 로 간주해 비교한다.
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


# ---- 식별자 생성 ----

def _new_customer_key() -> str:
    """토스 구매자 식별자. **추측 불가**해야 하고 개인정보를 담으면 안 된다.

    user_id 나 이메일을 쓰면 결제창에 그대로 노출되고, 남의 customerKey 를 추측해 빌링키 발급을
    시도할 여지가 생긴다. uuid4(무작위 122비트)를 쓴다.
    """
    return f"cus_{uuid.uuid4().hex}"


def _new_order_id() -> str:
    # payments.order_id 는 UNIQUE 라 중복 청구·중복 반영을 막는 열쇠다. 토스 규격은 6~64자.
    return f"ord_{uuid.uuid4().hex}"


def _order_name(plan: Plan) -> str:
    return f"{plan.label_ko} 요금제 1개월"


# ---- 결제수단(빌링키) ----

def get_billing_key(db: Session, user_id: int) -> BillingKey | None:
    return db.scalar(select(BillingKey).where(BillingKey.user_id == user_id))


def _ensure_paid_plan(db: Session, plan_code: str) -> Plan:
    """새로 **구매**하는 경로라 판매 중인 플랜만 허용한다 (get_purchasable_plan)."""
    plan = get_purchasable_plan(db, plan_code)

    if plan.price_krw <= 0:
        raise ValueError("무료 요금제는 결제가 필요하지 않습니다.")

    return plan


# ---- 1) 결제 준비 ----

def start_checkout(db: Session, user_id: int, plan_code: str) -> dict:
    """결제창에 넘길 값을 만든다. 카드 등록 전이라 청구도, 원장 기록도 하지 않는다.

    `customer_key` 는 이미 등록된 카드가 있으면 **재사용**한다 — 같은 회원이 토스 쪽에서 여러
    구매자로 갈라지지 않게 한다.
    """
    plan = _ensure_paid_plan(db, plan_code)
    # 키가 없으면 결제창을 띄울 수 없다(client_key 를 못 준다). 라우트가 503 으로 변환한다.
    toss_client.ensure_configured()

    existing = get_billing_key(db, user_id)
    customer_key = existing.customer_key if existing is not None else _new_customer_key()

    return {
        "customer_key": customer_key,
        "client_key": toss_client.TOSS_CLIENT_KEY,
        "plan_code": plan.code,
        # 앱은 이 금액을 **표시만** 한다. 실제 청구액은 confirm 에서 서버가 다시 정한다.
        "amount": plan.price_krw,
        "order_name": _order_name(plan),
    }


# ---- 2) 카드 등록 + 최초 청구 ----

def confirm_billing(
    db: Session, user_id: int, auth_key: str, customer_key: str, plan_code: str
) -> UserSubscription:
    """authKey → 빌링키 발급 → 저장 → 최초 청구 → 구독 활성화.

    청구가 실패하면 **구독을 활성화하지 않는다** — 결제 안 된 Premium 이 생기면 안 된다.
    빌링키 발급까지는 성공했을 수 있는데, 그 카드는 남겨 둔다(사용자가 다시 시도하면 재발급 없이
    쓸 수 있고, 카드 등록 자체가 과금은 아니다).

    **중복 confirm 은 청구하지 않고 현재 구독을 그대로 돌려준다** (`_is_duplicate_confirm`).
    이 경로는 호출마다 새 `order_id` 를 만들기 때문에 `order_id` UNIQUE 도 `_mark_payment_done`
    의 done 가드도 걸리지 않아, 방어가 없으면 한 달치가 두 번 청구된다(실측). 유일한 방어가
    "토스가 authKey 재사용을 거절해 준다"였는데, 그건 **결제사에 위임된 것**이고 결제창을 두 번
    완주하면 authKey 가 서로 달라 그마저 통하지 않는다.

    한계: 게이트와 청구 사이에 토스 HTTP 가 있어 구독 행을 잠근 채 통과할 수 없다(잠금을 쥔 채
    결제사를 기다리면 커넥션 풀이 마른다 — 아래 규약). 그래서 **완전히 동시에 도착한** confirm
    둘은 여전히 각자 청구할 수 있다. 실제 재호출 경로(새로고침·뒤로가기·502 후 재시도)는 전부
    순차라 이 게이트가 막는다.
    """
    plan = _ensure_paid_plan(db, plan_code)
    # 금액은 서버가 정한다. 클라이언트는 금액을 보내지 않고, 보내더라도 이 함수는 받지 않는다.
    amount = plan.price_krw
    subscription = get_subscription(db, user_id)

    if _is_duplicate_confirm(subscription, plan.code, datetime.now(UTC)):
        info_logger.info(f"billing confirm skip(duplicate) user_id={user_id} plan={plan.code}")
        return subscription

    issued = toss_client.issue_billing_key(auth_key, customer_key)
    _upsert_billing_key(db, user_id, customer_key, issued)

    payment = _create_ready_payment(db, user_id, plan, amount)
    # 원장을 **커밋한 뒤** 외부 HTTP 를 부른다 — 트랜잭션을 연 채 결제사를 기다리면 커넥션·행
    # 잠금이 붙잡혀 풀이 마른다 (SMS 연동에서 얻은 규약, 20장).
    db.commit()

    charge = _charge(db, payment, issued.billing_key, customer_key, plan)
    subscription = _activate_subscription(db, user_id, plan.code, datetime.now(UTC))
    _mark_payment_done(payment, charge)
    db.commit()
    info_logger.info(
        f"billing confirm ok user_id={user_id} plan={plan.code} order_id={payment.order_id}"
    )
    return subscription


def _is_duplicate_confirm(
    subscription: UserSubscription, plan_code: str, now: datetime
) -> bool:
    """이 confirm 이 "이미 이룬 결과를 다시 요청한 것"인가.

    셋을 모두 만족할 때만 중복이다 — **같은 플랜**의 **활성** 구독이고 **기간이 아직 남아 있다**.
    이 상태에서 또 청구하면 사용자는 이미 산 달을 한 번 더 사게 된다.

    통과시키는(= 청구하는) 경우와 그 이유:

    - **다른 플랜**: 업그레이드·변경이라 별개 결제다. 기간 중 업그레이드가 전액 재청구되는 것은
      감수한 결정이다 (DATA_MODEL.md 24장).
    - **`past_due`**: 갱신 청구가 실패한 상태다. 카드를 바꿔 다시 결제하려는 정당한 시도를
      막지 않는다 — 여기서 막으면 사용자가 스스로 복구할 길이 사라진다.
    - **`canceled`**: 해지 뒤 다시 구독하겠다는 의사표시다. 기간이 남은 채 재결제하면 이중 지불이
      되지만 그건 '재구독 정책'이지 이 게이트가 다룰 중복이 아니다 — 앱에는 경로도 없다(해당
      플랜 카드가 '사용 중'이라 구독 버튼을 그리지 않는다).
    - **기간이 없거나(`current_period_end is None`) 지난 경우**: 결제 이전에 부여된 구독이거나
      만료된 구독이라, 새로 사는 것이 맞다 (`get_effective_plan` 이 이미 lite 로 해석한다).
    """
    if subscription.plan_code != plan_code:
        return False

    if subscription.status != STATUS_ACTIVE:
        return False

    period_end = subscription.current_period_end

    return period_end is not None and _as_utc(period_end) > now


def _upsert_billing_key(
    db: Session, user_id: int, customer_key: str, issued: toss_client.IssuedBillingKey
) -> BillingKey:
    billing = get_billing_key(db, user_id)

    if billing is None:
        billing = BillingKey(user_id=user_id, customer_key=customer_key)
        db.add(billing)

    # EncryptedString 이 write 시 암호화한다 — 여기서는 평문을 그대로 넣는다(DB 에는 암호문).
    billing.billing_key = issued.billing_key
    billing.customer_key = customer_key
    billing.card_company = issued.card_company
    billing.card_number = issued.card_number
    billing.card_type = issued.card_type
    db.flush()
    return billing


def _create_ready_payment(db: Session, user_id: int, plan: Plan, amount: int) -> Payment:
    payment = Payment(
        user_id=user_id,
        order_id=_new_order_id(),
        plan_code=plan.code,
        amount=amount,
        status=PAYMENT_READY,
    )
    db.add(payment)
    db.flush()
    return payment


def _charge(
    db: Session, payment: Payment, billing_key: str, customer_key: str, plan: Plan
) -> toss_client.ChargeResult:
    """청구 1회. 실패하면 원장을 failed 로 확정하고 TossError 를 그대로 올린다."""
    try:
        return toss_client.charge_billing(
            billing_key=billing_key,
            customer_key=customer_key,
            amount=payment.amount,
            order_id=payment.order_id,
            order_name=_order_name(plan),
        )
    except TossError as error:
        _mark_payment_failed(payment, error)
        db.commit()
        raise


def _mark_payment_failed(payment: Payment, error: TossError) -> None:
    payment.status = PAYMENT_FAILED
    # 결제사 코드는 원장·로그에만 남는다(23장: fail_code 는 응답에 노출하지 않는다).
    payment.fail_code = error.code
    # fail_reason 은 GET /api/payments 로 사용자에게 나가는 필드다. 토스 원문이 아니라 우리가
    # 통제하는 한국어 메시지를 넣는다.
    payment.fail_reason = error.message[:255]


def _mark_payment_done(payment: Payment, charge: toss_client.ChargeResult) -> bool:
    """이미 `done` 인 주문은 다시 반영하지 않는다 — 멱등의 마지막 방어선.

    반환값 False 는 "이 호출이 아무것도 바꾸지 않았다"는 뜻이라, 호출자가 기간을 두 번 연장하는
    것을 막는 신호로 쓴다.
    """
    if payment.status == PAYMENT_DONE:
        return False

    payment.status = PAYMENT_DONE
    payment.payment_key = charge.payment_key
    payment.method = charge.method
    payment.approved_at = charge.approved_at or datetime.now(UTC)
    payment.fail_code = None
    payment.fail_reason = None
    return True


def _activate_subscription(
    db: Session, user_id: int, plan_code: str, base: datetime
) -> UserSubscription:
    subscription = get_subscription(db, user_id)
    period_end = add_one_month(base)
    subscription.plan_code = plan_code
    subscription.status = STATUS_ACTIVE
    subscription.current_period_end = period_end
    # 자동갱신이므로 다음 청구는 기간 종료 시각과 같다.
    subscription.next_billing_at = period_end
    subscription.cancel_at_period_end = False
    db.flush()
    return subscription


# ---- 3) 해지 ----

def cancel_billing(db: Session, user_id: int) -> UserSubscription:
    """자동갱신 해지. **기간(current_period_end)까지는 유료를 유지한다** — 이미 받은 돈에 대한
    이용권을 회수하지 않는다. 기간이 지나면 `get_effective_plan` 이 알아서 lite 로 해석한다.
    """
    subscription = get_subscription(db, user_id)
    plan = get_plan(db, subscription.plan_code)

    if plan.price_krw <= 0:
        raise ValueError("무료 요금제는 해지할 자동결제가 없습니다.")

    subscription.status = STATUS_CANCELED
    subscription.cancel_at_period_end = True
    # 다음 청구를 지운다 — 갱신 배치의 대상 조건에서 빠진다.
    subscription.next_billing_at = None
    db.commit()
    info_logger.info(f"billing cancel ok user_id={user_id} plan={plan.code}")
    return subscription


# ---- 4) 갱신 배치 ----

def charge_due_subscriptions(db: Session, now: datetime | None = None) -> dict:
    """청구 예정일이 지난 구독들을 청구한다 (cron: scripts/charge_due_subscriptions.py).

    **한 건의 실패가 배치를 죽이면 안 된다** — 회원 A 의 카드가 만료됐다고 B~Z 가 갱신되지 않으면
    그쪽이 더 큰 사고다. 그래서 건마다 예외를 잡고 다음 건으로 넘어간다.
    """
    now = now or datetime.now(UTC)
    due = list(
        db.scalars(
            select(UserSubscription).where(
                UserSubscription.next_billing_at.is_not(None),
                UserSubscription.next_billing_at <= now,
                UserSubscription.cancel_at_period_end.is_(False),
            )
        ).all()
    )
    result = {"due": len(due), "charged": 0, "failed": 0, "skipped": 0}

    for subscription in due:
        try:
            if _renew(db, subscription, now):
                result["charged"] += 1
            else:
                result["skipped"] += 1
        except TossError as error:
            # 청구 실패(카드 거절·결제사 장애). _renew 안에서 원장·구독 상태를 이미 확정했다.
            result["failed"] += 1
            error_logger.error(
                f"billing renew fail user_id={subscription.user_id} code={error.code}"
            )
        except Exception as error:  # noqa: BLE001 - 배치는 어떤 예외로도 멈추면 안 된다
            db.rollback()
            result["failed"] += 1
            error_logger.error(f"billing renew error user_id={subscription.user_id}: {error!r}")

    info_logger.info(
        f"billing renew batch due={result['due']} charged={result['charged']} "
        f"failed={result['failed']} skipped={result['skipped']}"
    )
    return result


def _renew(db: Session, subscription: UserSubscription, now: datetime) -> bool:
    """구독 1건 갱신. 청구했으면 True, 대상이 아니라 건너뛰었으면 False."""
    user_id = subscription.user_id
    # 기존 구독의 해석이라 get_plan 을 쓴다 — 판매 중단된(is_active=false) 플랜이어도 이미
    # 구독 중인 회원의 갱신은 계속돼야 한다 (20장의 get_plan/get_purchasable_plan 구분).
    plan = get_plan(db, subscription.plan_code)

    if plan.price_krw <= 0:
        # 무료인데 청구 예정이 남아 있는 건 데이터 이상이다. 청구하지 않고 예정만 지운다.
        subscription.next_billing_at = None
        db.commit()
        return False

    billing = get_billing_key(db, user_id)

    if billing is None:
        # 청구할 수단이 없다. 재시도해도 영원히 실패하므로 예정을 비우고 만료에 맡긴다.
        subscription.status = STATUS_PAST_DUE
        subscription.next_billing_at = None
        db.commit()
        error_logger.error(f"billing renew skip user_id={user_id}: 등록된 결제수단 없음")
        return False

    payment = _create_ready_payment(db, user_id, plan, plan.price_krw)
    db.commit()

    try:
        charge = toss_client.charge_billing(
            billing_key=billing.billing_key,
            customer_key=billing.customer_key,
            amount=payment.amount,
            order_id=payment.order_id,
            order_name=_order_name(plan),
        )
    except TossError as error:
        _mark_payment_failed(payment, error)
        _mark_past_due(subscription, now)
        db.commit()
        raise

    if not _mark_payment_done(payment, charge):
        # 같은 주문이 이미 반영돼 있으면 기간을 두 번 늘리지 않는다.
        db.commit()
        return False

    base = subscription.current_period_end or now
    period_end = _next_period_end(base, now)
    subscription.status = STATUS_ACTIVE
    subscription.current_period_end = period_end
    subscription.next_billing_at = period_end
    db.commit()
    info_logger.info(
        f"billing renew ok user_id={user_id} plan={plan.code} order_id={payment.order_id}"
    )
    return True


def _mark_past_due(subscription: UserSubscription, now: datetime) -> None:
    """갱신 실패 — 다음날 재시도한다. **기간은 줄이지 않는다**(유예).

    재시도는 청구 예정일(= current_period_end)로부터 BILLING_RETRY_MAX_DAYS 까지만 한다. 그 뒤엔
    예정을 비운다 — 기간이 지나면 어차피 lite 로 해석되므로 결제사를 매일 두드릴 이유가 없다.
    """
    subscription.status = STATUS_PAST_DUE
    retry_at = now + timedelta(days=BILLING_RETRY_INTERVAL_DAYS)
    period_end = subscription.current_period_end

    if period_end is None:
        subscription.next_billing_at = retry_at
        return

    deadline = _as_utc(period_end) + timedelta(days=BILLING_RETRY_MAX_DAYS)
    subscription.next_billing_at = retry_at if retry_at <= deadline else None
