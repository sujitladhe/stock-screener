"""
alembic/env.py — wires Alembic into OUR app, so it uses the same
DATABASE_URL (from app/config.py's .env-based settings) and the same
SQLAlchemy models (app/models.py) as the app itself, rather than a
separately maintained connection string or schema definition.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make sure every model is registered on Base.metadata before Alembic
# looks at it — importing app.models has the side effect of defining
# all the table classes (UserSession, Instrument, VolumeAverage,
# AngelSession, ScreenerDailyStat, etc.) on the shared Base.
from app.database import Base
from app import models  # noqa: F401 — import for side effect of registering tables
from app.config import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Use our app's real DB URL instead of whatever's (blank) in alembic.ini
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
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
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
