"""baseline - schema as it exists today, adopted into Alembic

This migration is DELIBERATELY EMPTY. Your database already has every
table in it (user_sessions, instruments, angel_session, volume_averages,
screener_daily_stats) created previously via SQLAlchemy's
Base.metadata.create_all() and manual ALTER TABLE statements — NOT
through any migration history.

This migration exists only as a starting point to "stamp" your
existing database against, so Alembic knows "the current DB matches
this point in history" without trying to (and failing to) re-create
tables that are already there.

DO NOT run "alembic upgrade head" as your first step. Run:
    alembic stamp head

This marks your database as being at this revision WITHOUT running any
SQL. From this point forward, every real schema change gets its own
proper migration (via alembic revision --autogenerate), applied with
"alembic upgrade head" as normal.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-08

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass  # deliberately empty — see module docstring


def downgrade() -> None:
    pass  # deliberately empty — see module docstring
