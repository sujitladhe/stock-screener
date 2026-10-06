"""new features: ignored stocks, auto expiry, day-high limit, circuit pct, candle pct

Revision ID: 0004_new_features
Revises: 0003_auto_trade_orders
Create Date: 2026-10-03
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_new_features"
down_revision = "0003_auto_trade_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------- ignored_stocks ------------------------------------------------
    op.create_table(
        "ignored_stocks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("trading_symbol", sa.String(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("ignored_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "client_id", "trading_symbol", "trade_date",
            name="uq_ignored_client_symbol_date",
        ),
    )
    op.create_index("ix_ignored_stocks_client_id", "ignored_stocks", ["client_id"])

    # ---------- orders --------------------------------------------------------
    op.add_column(
        "orders",
        sa.Column("auto_expires_daily", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "orders",
        sa.Column("auto_day_high_pct_limit", sa.Numeric(), nullable=True),
    )

    # ---------- screener_daily_stats ------------------------------------------
    op.add_column("screener_daily_stats", sa.Column("last_circuit_pct", sa.Integer(), nullable=True))
    op.add_column("screener_daily_stats", sa.Column("last_candle_pct", sa.Numeric(), nullable=True))


def downgrade() -> None:
    op.drop_column("screener_daily_stats", "last_candle_pct")
    op.drop_column("screener_daily_stats", "last_circuit_pct")
    op.drop_column("orders", "auto_day_high_pct_limit")
    op.drop_column("orders", "auto_expires_daily")
    op.drop_index("ix_ignored_stocks_client_id", table_name="ignored_stocks")
    op.drop_table("ignored_stocks")
