"""Add candles_last_synced_date to instruments table.

Tracks the calendar date on which sync_daily_candles.py last ran for
each stock. The sync script uses this to skip stocks it already
processed today — regardless of what candle dates are stored — so a
second run on the same day is nearly instant.

Revision ID: 0007_candle_sync_tracking
Revises: 0006_daily_candles
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa


revision = "0007_candle_sync_tracking"
down_revision = "0006_daily_candles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "instruments",
        sa.Column("candles_last_synced_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("instruments", "candles_last_synced_date")
