from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from crypto import EncryptedString
from database import Base


class Plan(Base):
    """요금제 참조 테이블 (DATA_MODEL.md 10장 규칙 — 릴리즈 없이 가격·한도를 조정한다)."""

    __tablename__ = "plans"

    # lite / pro / premium
    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    label_ko: Mapped[str] = mapped_column(String(30), nullable=False)
    # 0 = 무료(lite). 표시용이며 결제 연동 전까지 과금에 쓰이지 않는다.
    price_krw: Mapped[int] = mapped_column(Integer, nullable=False)
    # 비전 LLM(/api/predict) 일일 호출 상한. KST 자정 리셋.
    daily_vision_quota: Mapped[int] = mapped_column(Integer, nullable=False)
    # 내가 만든 그룹에 "본인 말고" 추가할 수 있는 인원. 정원 = 이 값 + 1(owner).
    max_group_members: Mapped[int] = mapped_column(Integer, nullable=False)
    max_pets: Mapped[int] = mapped_column(Integer, nullable=False)
    # 그룹을 여러 개 만들어 인원 제한을 우회하는 것을 막는다.
    max_owned_groups: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)


class UserSubscription(Base):
    """회원 1 : 요금제 1. user_id 를 PK 로 두어 1:1을 스키마로 강제한다."""

    __tablename__ = "user_subscriptions"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    plan_code: Mapped[str] = mapped_column(ForeignKey("plans.code"), index=True, nullable=False)
    # ---- 자동결제(토스 빌링) 상태. 무료(lite)는 전부 기본값(만료·청구 없음). ----
    # active | canceled(자동갱신 해지 — 기간 만료까지는 유료 유지) | past_due(갱신 실패)
    status: Mapped[str] = mapped_column(String(20), server_default=text("'active'"), nullable=False)
    # 유료 구독의 현재 결제 기간 종료 시각. 이 시각 이후엔 lite 로 강등한다(무료는 null).
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 다음 자동청구 예정 시각(자동갱신 아니면 null).
    next_billing_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 사용자가 자동갱신을 껐는지(기간 만료까지는 유료 유지).
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class VisionUsageDaily(Base):
    """비전 LLM 일일 사용량 카운터 (user_id + KST 날짜).

    호출 로그를 COUNT 하지 않고 카운터 행을 두는 이유는, 한도 판정과 증가를 한 문장의
    UPSERT 로 원자화하기 위해서다 (동시 요청이 한도를 넘겨 통과하는 경합을 막는다).
    """

    __tablename__ = "vision_usage_daily"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    # KST 기준 날짜. UTC 로 저장하면 한국 사용자의 자정 리셋 체감과 9시간 어긋난다.
    usage_date: Mapped[date] = mapped_column(Date, primary_key=True)
    used_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class BillingKey(Base):
    """자동결제(토스 빌링) 결제수단. 회원당 1개(활성). `billing_key` 는 이 값만으로 카드를
    청구할 수 있는 **민감정보**라 앱 레이어 AES-GCM 으로 암호화 저장한다(EncryptedString).
    로그·응답에 평문 노출 금지. 카드 표시는 마스킹된 번호·카드사만 쓴다.
    """

    __tablename__ = "billing_keys"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    # 토스 billingKey (DB 에는 암호문으로 저장). 청구 시에만 복호화해 쓴다.
    billing_key: Mapped[str] = mapped_column(EncryptedString(512), nullable=False)
    # 토스 customerKey (구매자 식별자, 청구 시 함께 보낸다). 개인정보 아님.
    customer_key: Mapped[str] = mapped_column(String(64), nullable=False)
    card_company: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # 마스킹된 카드번호(토스가 마스킹해 준다). 앞6·뒤4만.
    card_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    card_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Payment(Base):
    """결제 원장 — 최초/갱신 청구 1건마다 1행. 감사·정산 근거이자 멱등 장치다
    (`order_id` UNIQUE 로 같은 주문의 중복 반영을 막는다).

    **행을 지우지 않는다.** 회원이 탈퇴해도 거래 기록은 남기고 `user_id` 만 NULL 로 끊는다
    (`account_service.delete_account`) — 개인정보는 파기하면서 대금결제 기록은 보존하기 위함이다.
    """

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # NULL = 탈퇴 회원의 익명화된 원장. 청구 시점에는 언제나 값이 있다(_create_ready_payment).
    # 조회는 user_id 일치로만 하므로(payment_service) 익명화된 행은 누구에게도 노출되지 않는다.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    # 서버가 생성해 토스에 보낸 주문번호. UNIQUE 로 중복 청구·중복 반영을 막는다.
    order_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    plan_code: Mapped[str] = mapped_column(ForeignKey("plans.code"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    # ready | done | failed | canceled
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # 토스 paymentKey (청구 성공 시). 취소·조회에 쓴다.
    payment_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fail_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fail_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
