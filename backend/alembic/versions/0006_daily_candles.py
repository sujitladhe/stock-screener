"""daily_candles table — stores per-stock daily OHLCV candle data
for use in DB-level scans (e.g. volume breakouts, price patterns).

Revision ID: 0006_daily_candles
Revises: 0005_screener_settings
Create Date: 2026-10-18
"""
from alembic import op
import sqlalchemy as sa


revision = "0006_daily_candles"
down_revision = "0005_screener_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_candles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("instrument_id", sa.Integer(), nullable=False, index=True),
        sa.Column("trading_symbol", sa.String(), nullable=False, index=True),
        sa.Column("candle_date", sa.Date(), nullable=False, index=True),
        sa.Column("open", sa.Numeric(), nullable=False),
        sa.Column("high", sa.Numeric(), nullable=False),
        sa.Column("low", sa.Numeric(), nullable=False),
        sa.Column("close", sa.Numeric(), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("instrument_id", "candle_date", name="uq_instrument_candle_date"),
    )


def downgrade() -> None:
    op.drop_table("daily_candles")
