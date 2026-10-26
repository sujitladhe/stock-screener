"""Add EMA columns to daily_candles.

Revision ID: 0008_ema_columns
Revises: 0007_candle_sync_tracking
Create Date: 2026-10-21

Adds five new nullable Numeric columns to daily_candles:
  ema_10, ema_20, ema_50, ema_100, ema_200

All are nullable so existing rows stay valid with NULLs.
The sync script fills them in on its next run (full backfill on first
run, incremental from then on).
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_ema_columns"
down_revision = "0007_candle_sync_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("daily_candles", sa.Column("ema_10",  sa.Numeric, nullable=True))
    op.add_column("daily_candles", sa.Column("ema_20",  sa.Numeric, nullable=True))
    op.add_column("daily_candles", sa.Column("ema_50",  sa.Numeric, nullable=True))
    op.add_column("daily_candles", sa.Column("ema_100", sa.Numeric, nullable=True))
    op.add_column("daily_candles", sa.Column("ema_200", sa.Numeric, nullable=True))


def downgrade() -> None:
    op.drop_column("daily_candles", "ema_200")
    op.drop_column("daily_candles", "ema_100")
    op.drop_column("daily_candles", "ema_50")
    op.drop_column("daily_candles", "ema_20")
    op.drop_column("daily_candles", "ema_10")
