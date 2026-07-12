import os
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# .env를 환경변수로 로드한다 (cwd 기준 — 저장소 루트에서 실행할 것). 예전엔 gpt_oss_service가
# 이 역할을 했으나 제거되어, 설정을 읽는 최하위 모듈에서 직접 로드한다 (load_dotenv는 멱등).
load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://kcal:kcal@localhost:5432/kcal",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    import models.auth_model  # noqa: F401
    import models.consent_model  # noqa: F401
    import models.group_model  # noqa: F401
    import models.health_model  # noqa: F401
    import models.meta_model  # noqa: F401
    import models.pet_model  # noqa: F401
    import models.recommendation_model  # noqa: F401

    Base.metadata.create_all(bind=engine)
