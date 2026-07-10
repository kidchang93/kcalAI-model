import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


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

    Base.metadata.create_all(bind=engine)
