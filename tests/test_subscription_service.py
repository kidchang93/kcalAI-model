"""요금제·쿼터 회귀 (DATA_MODEL.md 20장).

카카오 회원번호는 다른 테스트와 겹치지 않도록 82000000xx 대역을 쓴다.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from models.auth_model import User
from models.subscription_model import Plan, UserSubscription, VisionUsageDaily
from services import auth_service, group_service, pet_service, subscription_service
from services.subscription_service import PlanLimitError
from timeutil import UTC, today_kst


def _make_user(db, kakao_id: str) -> User:
    user = User(kakao_id=kakao_id, nickname="테스터")
    db.add(user)
    db.commit()
    return user


def _grant_paid_plan(db, user_id: int, plan_code: str) -> None:
    """유료 플랜을 부여하는 테스트 셋업 — 결제 경로(billing_service.confirm_billing)의 대역이다.

    `change_plan` 으로는 더 이상 유료 전환을 할 수 없다 (24장: 결제를 거쳐야 한다). 여기 테스트들이
    보려는 건 '유료 회원의 한도'이지 결제 흐름이 아니므로, 구독 행을 결제 성공 후와 같은 상태로
    직접 만든다. 결제 흐름 자체는 tests/test_billing_service.py 가 덮는다.
    """
    subscription = subscription_service.get_subscription(db, user_id)
    subscription.plan_code = plan_code
    subscription.status = "active"
    subscription.current_period_end = datetime.now(UTC) + timedelta(days=30)
    subscription.next_billing_at = subscription.current_period_end
    subscription.cancel_at_period_end = False
    db.commit()


def _signup(db, kakao_id: str, plan_code: str | None = None) -> User:
    raw_code, _ = auth_service.create_link_code(db, kakao_id, "테스터")
    user, _, _ = auth_service.kakao_signup(db, raw_code, True, True, plan_code)
    return user


# ---- 가입 시 요금제 부여 ----
# (가입 흐름 자체는 tests/test_auth_service.py 가 덮는다. 여기서는 요금제 결합만 본다.)

def test_signup_grants_free_plan_by_default(db):
    user = _signup(db, "82000000001")

    assert subscription_service.get_subscription(db, user.id).plan_code == "lite"


def test_signup_paid_plan_still_starts_free(db):
    # 가입의 plan_code 로 유료를 부여하면 결제 없이 Premium 을 얻는 경로가 된다.
    # 유료 선택은 의사표시로만 받고 무료로 시작한다 — 업그레이드는 결제(billing/confirm)뿐.
    user = _signup(db, "82000000002", "premium")

    assert subscription_service.get_subscription(db, user.id).plan_code == "lite"
    assert subscription_service.get_user_plan(db, user.id).code == "lite"


def test_signup_with_unknown_plan_is_rejected(db):
    with pytest.raises(ValueError):
        _signup(db, "82000000004", "enterprise")


def test_missing_subscription_self_heals_to_free_plan(db):
    # 0014 이전 가입자(구독 행 없음)도 한도 판정이 500 으로 죽지 않는다.
    user = _make_user(db, "82000000005")

    assert subscription_service.get_user_plan(db, user.id).code == "lite"

    # 자기치유는 **저장**돼야 한다. flush 만 하면 읽기 전용 경로에서 세션 종료와 함께 롤백되어
    # 매 요청 재삽입된다 — 커밋됐는지 확인한다.
    db.expire_all()
    assert db.get(UserSubscription, user.id) is not None


# ---- 비전 일일 쿼터 ----

def test_free_plan_allows_five_vision_calls_then_402(db):
    user = _make_user(db, "82000000010")

    for expected in (1, 2, 3, 4, 5):
        used, limit, _ = subscription_service.consume_vision_quota(db, user.id)
        assert (used, limit) == (expected, 5)

    with pytest.raises(PlanLimitError) as raised:
        subscription_service.consume_vision_quota(db, user.id)

    assert raised.value.resource == "vision_daily"
    assert raised.value.plan_code == "lite"
    assert raised.value.limit == 5


def test_refund_returns_the_reserved_call(db):
    user = _make_user(db, "82000000011")

    subscription_service.consume_vision_quota(db, user.id)
    _, _, usage_date = subscription_service.consume_vision_quota(db, user.id)
    assert subscription_service.get_vision_usage(db, user.id) == 2

    # 인식 백엔드 장애(503)로 선차감을 되돌린 상황.
    subscription_service.refund_vision_quota(db, user.id, usage_date)
    assert subscription_service.get_vision_usage(db, user.id) == 1


def test_refund_targets_the_consumed_day_not_today(db):
    # 자정을 걸친 요청: 어제 차감한 건은 어제 카운터에서 빠져야 한다.
    user = _make_user(db, "82000000013")
    yesterday = today_kst() - timedelta(days=1)

    db.add(VisionUsageDaily(user_id=user.id, usage_date=yesterday, used_count=2))
    subscription_service.consume_vision_quota(db, user.id)  # 오늘 1건
    db.commit()

    subscription_service.refund_vision_quota(db, user.id, yesterday)

    assert subscription_service.get_vision_usage(db, user.id, yesterday) == 1
    # 오늘 쓴 정상 사용분은 건드리지 않는다.
    assert subscription_service.get_vision_usage(db, user.id) == 1


def test_upgrade_raises_the_daily_quota(db):
    user = _make_user(db, "82000000012")

    for _ in range(5):
        subscription_service.consume_vision_quota(db, user.id)

    with pytest.raises(PlanLimitError):
        subscription_service.consume_vision_quota(db, user.id)

    _grant_paid_plan(db, user.id, "pro")

    # 사용량은 유지되고 한도만 올라간다 (6번째 호출이 통과한다).
    used, limit, _ = subscription_service.consume_vision_quota(db, user.id)
    assert (used, limit) == (6, 30)


# ---- 요금제 판매 중단 (is_active) ----

def test_deactivated_plan_still_serves_existing_subscribers(db):
    """판매 중단은 '신규 선택 차단'이지 '기존 구독 무효화'가 아니다."""
    user = _make_user(db, "82000000050")
    _grant_paid_plan(db, user.id, "pro")

    plan = db.get(Plan, "pro")
    plan.is_active = False
    db.commit()

    # 기존 Pro 회원은 계속 Pro 한도로 동작한다 (여기서 깨지면 predict 가 500 이 된다).
    assert subscription_service.get_user_plan(db, user.id).code == "pro"
    used, limit, _ = subscription_service.consume_vision_quota(db, user.id)
    assert limit == 30

    # 목록·신규 선택에서는 사라진다. (선택 차단의 seam 은 get_purchasable_plan 이다 — change_plan 은
    # 24장 이후 유료 전환 자체를 막으므로 is_active 를 검증하지 못한다.)
    assert "pro" not in {item["code"] for item in subscription_service.list_plans_view(db)["plans"]}

    with pytest.raises(ValueError):
        subscription_service.get_purchasable_plan(db, "pro")


# ---- 그룹·반려동물 한도 ----

def test_free_plan_allows_one_owned_group(db):
    owner = _make_user(db, "82000000020")
    group_service.create_group(db, owner.id, "우리집", "family")

    with pytest.raises(PlanLimitError) as raised:
        group_service.create_group(db, owner.id, "친구들", "friends")

    assert raised.value.resource == "owned_groups"


def test_group_capacity_is_judged_by_owner_plan(db):
    owner = _make_user(db, "82000000021")
    first = _make_user(db, "82000000022")
    second = _make_user(db, "82000000023")

    summary = group_service.create_group(db, owner.id, "우리집", "family")
    invite_code = summary["invite_code"]

    # lite = 본인 제외 1명. 첫 참여자는 들어오고, 두 번째는 막힌다.
    group_service.join_group(db, first.id, invite_code)

    with pytest.raises(PlanLimitError) as raised:
        group_service.join_group(db, second.id, invite_code)

    assert raised.value.resource == "group_members"
    assert raised.value.limit == 1

    # 소유자가 업그레이드하면 정원이 늘어난다 (참여자 요금제와 무관하다).
    _grant_paid_plan(db, owner.id, "pro")
    joined = group_service.join_group(db, second.id, invite_code)
    assert joined["member_count"] == 3


def test_free_plan_allows_one_pet(db):
    owner = _make_user(db, "82000000030")
    pet_service.create_pet(db, owner.id, "콩이", "dog", None, None, None, None)

    with pytest.raises(PlanLimitError) as raised:
        pet_service.create_pet(db, owner.id, "나비", "cat", None, None, None, None)

    assert raised.value.resource == "pets"


def test_soft_deleted_pet_frees_a_slot(db):
    owner = _make_user(db, "82000000031")
    pet = pet_service.create_pet(db, owner.id, "콩이", "dog", None, None, None, None)

    pet_service.soft_delete_pet(db, owner.id, pet["id"])

    # 삭제했으면 자리가 비는 게 맞다.
    pet_service.create_pet(db, owner.id, "나비", "cat", None, None, None, None)


def test_downgrade_keeps_existing_data_and_only_blocks_additions(db):
    owner = _make_user(db, "82000000040")
    _grant_paid_plan(db, owner.id, "pro")

    pet_service.create_pet(db, owner.id, "콩이", "dog", None, None, None, None)
    pet_service.create_pet(db, owner.id, "나비", "cat", None, None, None, None)
    pet_service.create_pet(db, owner.id, "구름", "dog", None, None, None, None)

    subscription_service.change_plan(db, owner.id, "lite")

    # 이미 만든 펫 3마리는 그대로 남는다 (서버가 말없이 지우지 않는다).
    assert len(pet_service.list_pets(db, owner.id)) == 3

    # 추가만 막힌다.
    with pytest.raises(PlanLimitError):
        pet_service.create_pet(db, owner.id, "초코", "dog", None, None, None, None)

