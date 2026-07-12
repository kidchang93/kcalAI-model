"""pytest 공용 픽스처.

테스트는 Postgres에 붙는다 — 인증 로직이 tz-aware datetime(쿨다운·만료)을 다뤄
SQLite로는 충실도가 떨어지기 때문이다. 각 테스트는 외부 트랜잭션 안에서 돌고,
서비스 내부 commit은 SAVEPOINT로 흡수한 뒤 종료 시 전부 롤백한다 —
그래서 대상 DB(기본은 개발 DB)를 오염시키지 않는다.

전용 테스트 DB를 쓰려면 TEST_DATABASE_URL을 지정한다.
"""

import os

import pytest
from sqlalchemy import create_engine
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
    yield engine
    engine.dispose()


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


@pytest.fixture(autouse=True)
def _force_dev_code(monkeypatch):
    # 발급된 평문 코드를 테스트가 받을 수 있도록 강제한다 (환경변수와 무관하게 결정적).
    # 운영 설정 게이트 테스트는 이 값을 각자 다시 덮어쓴다.
    import services.auth_service as auth_service

    monkeypatch.setattr(auth_service, "AUTH_INCLUDE_DEV_CODE", True)
