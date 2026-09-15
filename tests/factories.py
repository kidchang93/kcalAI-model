"""테스트 전용 데이터 팩토리.

여러 테스트 파일에 복제되어 있던 `User(...)`·`Payment(...)` 생성 보일러플레이트를 모은다.
`db.flush()`까지만 한다 — conftest의 SAVEPOINT 세션 안에서는 flush만으로도 같은 세션 내
조회에 값이 보이고, `db.commit()`은 SAVEPOINT를 해제·재시작할 뿐이라 결과는 같다.
"""

from models.auth_model import User
from models.subscription_model import Payment


def make_user(db, kakao_id: str = "test-user", nickname: str = "테스터", **extra) -> User:
    user = User(kakao_id=kakao_id, nickname=nickname, **extra)
    db.add(user)
    db.flush()
    return user


def make_payment(
    db,
    user_id: int | None,
    order_id: str,
    *,
    plan_code: str = "pro",
    amount: int = 5000,
    status: str = "done",
    method: str | None = "카드",
    **extra,
) -> Payment:
    payment = Payment(
        user_id=user_id,
        order_id=order_id,
        plan_code=plan_code,
        amount=amount,
        status=status,
        method=method,
        **extra,
    )
    db.add(payment)
    db.flush()
    return payment
