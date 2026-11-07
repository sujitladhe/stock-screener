"""nifty_candles_5min table - NIFTY 50 index 5-minute candles for backtesting.

Revision ID: 0012_nifty_candles_5min
Revises: 0011_options_history
Create Date: 2026-11-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_nifty_candles_5min"
down_revision = "0011_options_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nifty_candles_5min",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(), nullable=False, server_default="NIFTY"),
        sa.Column("candle_ts", sa.DateTime(), nullable=False),  # IST wall-clock, candle START time
        sa.Column("open", sa.Numeric(12, 2), nullable=False),
        sa.Column("high", sa.Numeric(12, 2), nullable=False),
        sa.Column("low", sa.Numeric(12, 2), nullable=False),
        sa.Column("close", sa.Numeric(12, 2), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("symbol", "candle_ts", name="uq_nifty5m_symbol_ts"),
    )
    op.create_index("ix_nifty5m_candle_ts", "nifty_candles_5min", ["candle_ts"])


def downgrade() -> None:
    op.drop_index("ix_nifty5m_candle_ts", table_name="nifty_candles_5min")
    op.drop_table("nifty_candles_5min")
