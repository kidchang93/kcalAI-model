import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# alembic 을 저장소 루트 밖에서 실행해도 애플리케이션 모듈을 import 할 수 있도록
# 저장소 루트(= 이 파일의 상위 디렉토리)를 경로에 추가한다.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# database 와 models 만 import 한다. services 를 건드리면 YOLO 로드와 HF_TOKEN 조회가
# 일어나므로 마이그레이션 단계에서는 절대 import 하지 않는다.
from database import DATABASE_URL, Base  # noqa: E402
import models.auth_model  # noqa: E402,F401
import models.consent_model  # noqa: E402,F401
import models.health_model  # noqa: E402,F401

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# .env / 환경변수에서 읽은 DATABASE_URL 을 단일 진실로 쓴다. alembic.ini 에 자격증명을
# 중복해서 두지 않는다.
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
