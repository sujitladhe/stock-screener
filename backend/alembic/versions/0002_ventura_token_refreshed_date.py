"""add ventura_token_refreshed_date to user_sessions

Supports the day-boundary relogin fix: get_current_session now forces
a fresh Ventura login whenever this date isn't today's IST date, on
top of the existing auth_expiry check — a real login failure was
observed on an order placed after a session had sat unused for a
while, and Ventura's docs don't explicitly confirm whether a token is
expected to remain valid across trading days.

Revision ID: 0002_ventura_token_refreshed_date
Revises: 0001_baseline
Create Date: 2026-09-19

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0002_ventura_token_refreshed_date"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_sessions",
        sa.Column("ventura_token_refreshed_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_sessions", "ventura_token_refreshed_date")
