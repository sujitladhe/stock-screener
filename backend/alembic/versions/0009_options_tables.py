"""Create options feature tables.

Revision ID: 0009_options_tables
Revises: 0008_ema_columns
Create Date: 2026-10-30

Adds four new tables for the NIFTY Option Dashboard:
  option_instrument_master  — NFO instrument list from Angel One
  option_eod_snapshot       — daily OI snapshot per strike/expiry
  option_daily_summary      — PCR / max-pain / IV summary per date
  option_guidance_log       — hourly guidance engine output (time-series)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009_options_tables"
down_revision = "0008_ema_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── option_instrument_master ──────────────────────────────────────────
    op.create_table(
        "option_instrument_master",
        sa.Column("id",            sa.Integer, primary_key=True),
        sa.Column("token",         sa.String(20),  nullable=False),
        sa.Column("symbol",        sa.String(50),  nullable=False),
        sa.Column("name",          sa.String(20),  nullable=False),
        sa.Column("expiry",        sa.Date,        nullable=False),
        sa.Column("strike",        sa.Integer,     nullable=False),
        sa.Column("option_type",   sa.String(2),   nullable=False),  # CE / PE
        sa.Column("lot_size",      sa.Integer,     nullable=True),
        sa.Column("fetched_at",    sa.DateTime,    nullable=True),
    )
    op.create_index(
        "ix_opt_master_token",
        "option_instrument_master", ["token"], unique=True
    )
    op.create_index(
        "ix_opt_master_expiry_strike",
        "option_instrument_master", ["expiry", "strike", "option_type"]
    )

    # ── option_eod_snapshot ───────────────────────────────────────────────
    op.create_table(
        "option_eod_snapshot",
        sa.Column("id",          sa.Integer, primary_key=True),
        sa.Column("date",        sa.Date,    nullable=False),
        sa.Column("expiry",      sa.Date,    nullable=False),
        sa.Column("strike",      sa.Integer, nullable=False),
        sa.Column("option_type", sa.String(2), nullable=False),
        sa.Column("token",       sa.String(20), nullable=True),
        sa.Column("oi",          sa.BigInteger, nullable=True),
        sa.Column("volume",      sa.BigInteger, nullable=True),
        sa.Column("ltp",         sa.Numeric(10, 2), nullable=True),
        sa.Column("saved_at",    sa.DateTime, nullable=True),
    )
    op.create_unique_constraint(
        "uq_option_eod_date_expiry_strike",
        "option_eod_snapshot",
        ["date", "expiry", "strike", "option_type"],
    )
    op.create_index(
        "ix_opt_eod_date",
        "option_eod_snapshot", ["date"]
    )

    # ── option_daily_summary ──────────────────────────────────────────────
    op.create_table(
        "option_daily_summary",
        sa.Column("id",              sa.Integer, primary_key=True),
        sa.Column("date",            sa.Date,    nullable=False, unique=True),
        sa.Column("expiry",          sa.Date,    nullable=True),
        sa.Column("pcr",             sa.Numeric(8, 4), nullable=True),
        sa.Column("max_pain",        sa.Integer, nullable=True),
        sa.Column("atm_iv",          sa.Numeric(8, 4), nullable=True),
        sa.Column("iv_skew",         sa.Numeric(8, 4), nullable=True),
        sa.Column("expected_move",   sa.Numeric(10, 2), nullable=True),
        sa.Column("total_ce_oi",     sa.BigInteger, nullable=True),
        sa.Column("total_pe_oi",     sa.BigInteger, nullable=True),
        sa.Column("spot_close",      sa.Numeric(10, 2), nullable=True),
        sa.Column("saved_at",        sa.DateTime, nullable=True),
    )

    # ── option_guidance_log ───────────────────────────────────────────────
    op.create_table(
        "option_guidance_log",
        sa.Column("id",               sa.Integer, primary_key=True),
        sa.Column("logged_at",        sa.DateTime, nullable=False),
        sa.Column("expiry",           sa.Date,     nullable=True),
        sa.Column("spot",             sa.Numeric(10, 2), nullable=True),
        sa.Column("score",            sa.Integer,  nullable=True),
        sa.Column("bias",             sa.String(20), nullable=True),
        sa.Column("confidence",       sa.Integer,  nullable=True),
        sa.Column("pcr",              sa.Numeric(8, 4), nullable=True),
        sa.Column("max_pain",         sa.Integer,  nullable=True),
        sa.Column("iv_skew",          sa.Numeric(8, 4), nullable=True),
        sa.Column("signal_breakdown", JSONB,       nullable=True),
    )
    op.create_index(
        "ix_opt_guidance_logged_at",
        "option_guidance_log", ["logged_at"]
    )


def downgrade() -> None:
    op.drop_table("option_guidance_log")
    op.drop_table("option_daily_summary")
    op.drop_table("option_eod_snapshot")
    op.drop_table("option_instrument_master")
