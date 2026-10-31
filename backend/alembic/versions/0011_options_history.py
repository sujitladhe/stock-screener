"""options history: 1-minute snapshots + decision log.

Adds two tables for the stateful Option Guidance Engine:
  option_minute_snapshot  - one row per strike per minute (price, OI, volume, spot)
  option_decision_log     - every 5-minute decision the engine makes, plus what
                            NIFTY did afterwards (filled in automatically later)

Revision ID: 0011_options_history
Revises: 0010_fix_options_tables
Create Date: 2026-10-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0011_options_history"
down_revision = "0010_fix_options_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "option_minute_snapshot",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("bucket_ts", sa.DateTime, nullable=False),
        sa.Column("expiry", sa.Date, nullable=False),
        sa.Column("strike", sa.Integer, nullable=False),
        sa.Column("spot", sa.Numeric(10, 2), nullable=True),
        sa.Column("ce_ltp", sa.Numeric(12, 2), nullable=True),
        sa.Column("pe_ltp", sa.Numeric(12, 2), nullable=True),
        sa.Column("ce_oi", sa.BigInteger, nullable=True),
        sa.Column("pe_oi", sa.BigInteger, nullable=True),
        sa.Column("ce_volume", sa.BigInteger, nullable=True),
        sa.Column("pe_volume", sa.BigInteger, nullable=True),
        sa.UniqueConstraint("bucket_ts", "expiry", "strike", name="uq_option_minute_ts_expiry_strike"),
    )
    op.create_index("ix_option_minute_ts", "option_minute_snapshot", ["bucket_ts"])

    op.create_table(
        "option_decision_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("decided_at", sa.DateTime, nullable=False),
        sa.Column("expiry", sa.Date, nullable=True),
        sa.Column("spot", sa.Numeric(10, 2), nullable=True),
        sa.Column("raw_score", sa.Integer, nullable=True),
        sa.Column("raw_bias", sa.String(20), nullable=True),
        sa.Column("bias", sa.String(20), nullable=True),
        sa.Column("pending_bias", sa.String(20), nullable=True),
        sa.Column("pending_count", sa.Integer, nullable=True),
        sa.Column("confidence", sa.Integer, nullable=True),
        sa.Column("metrics", JSONB, nullable=True),
        sa.Column("signals", JSONB, nullable=True),
        sa.Column("opportunities", JSONB, nullable=True),
        sa.Column("spike_alerts", JSONB, nullable=True),
        sa.Column("spot_15m", sa.Numeric(10, 2), nullable=True),
        sa.Column("spot_30m", sa.Numeric(10, 2), nullable=True),
        sa.Column("spot_60m", sa.Numeric(10, 2), nullable=True),
        sa.Column("high_60m", sa.Numeric(10, 2), nullable=True),
        sa.Column("low_60m", sa.Numeric(10, 2), nullable=True),
        sa.Column("outcome_done", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_option_decision_log_decided_at", "option_decision_log", ["decided_at"])


def downgrade() -> None:
    op.drop_index("ix_option_decision_log_decided_at", table_name="option_decision_log")
    op.drop_table("option_decision_log")
    op.drop_index("ix_option_minute_ts", table_name="option_minute_snapshot")
    op.drop_table("option_minute_snapshot")
