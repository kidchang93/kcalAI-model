"""pytest 공용 픽스처.

테스트는 Postgres에 붙는다 — 인증 로직이 tz-aware datetime(쿨다운·만료)을 다뤄
SQLite로는 충실도가 떨어지기 때문이다. 각 테스트는 외부 트랜잭션 안에서 돌고,
서비스 내부 commit은 SAVEPOINT로 흡수한 뒤 종료 시 전부 롤백한다 —
그래서 대상 DB(기본은 개발 DB)를 오염시키지 않는다.

전용 테스트 DB를 쓰려면 TEST_DATABASE_URL을 지정한다.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# auth_model만 import한다 → Base.metadata에는 auth 3테이블만 등록되고,
# create_all이 다른 모델(JSONB 등)을 건드리지 않는다.
import models.auth_model  # noqa: F401
from database import Base

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    os.getenv("DATABASE_URL", "postgresql+psycopg2://kcal:kcal@localhost:5432/kcal"),
)


@pytest.fixture(scope="session")
def _engine():
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    # checkfirst 기본값이라 이미 존재하는 테이블은 건너뛴다 (개발 DB에서도 안전).
    Base.metadata.create_all(bind=engine)
    _seed_plans(engine)
    yield engine
    engine.dispose()


def _seed_plans(engine) -> None:
    """요금제 시드 — 없으면 채운다 (멱등).

    `create_all`은 테이블만 만들고 시드는 넣지 않는다. 그래서 TEST_DATABASE_URL로 **깨끗한 DB**를
    쓰면 `plans`가 비어 한도 판정이 전부 "존재하지 않는 요금제입니다"로 깨진다 — 지금까지 통과한
    건 개발 DB에 0014를 이미 올려둔 덕이었다. 값은 alembic 0014·DATA_MODEL.md 20장과 같다.
    """
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO plans (code, label_ko, price_krw, daily_vision_quota, "
                "max_group_members, max_pets, max_owned_groups, sort_order, is_active) VALUES "
                "('lite', 'Lite', 0, 3, 1, 1, 1, 1, true), "
                "('pro', 'Pro', 5000, 30, 5, 5, 3, 2, true), "
                "('premium', 'Premium', 10000, 100, 10, 10, 5, 3, true) "
                "ON CONFLICT (code) DO NOTHING"
            )
        )


@pytest.fixture
def db(_engine):
    connection = _engine.connect()
    transaction = connection.begin()
    # join_transaction_mode="create_savepoint": 서비스가 db.commit()을 호출해도
    # SAVEPOINT만 릴리스되고 외부 트랜잭션은 유지된다. 종료 시 rollback으로 전부 되돌린다.
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()




