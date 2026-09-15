import os
from datetime import datetime
from typing import Annotated, Generator

from dotenv import load_dotenv
from sqlalchemy import DateTime, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Session, mapped_column, sessionmaker

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


# DB 가 채우는 시각 컬럼 (`Mapped[CreatedAt]`). 인덱스가 필요하면 `= mapped_column(index=True)`를 덧붙인다.
CreatedAt = Annotated[
    datetime, mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
]
UpdatedAt = Annotated[
    datetime,
    mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False),
]


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    import models  # noqa: F401 — 패키지 import 가 전 모델을 Base.metadata 에 등록한다

    Base.metadata.create_all(bind=engine)
