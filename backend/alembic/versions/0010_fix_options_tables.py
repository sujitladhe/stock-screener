"""Fix options tables — correct column layout to match SQLAlchemy models.

The previous migration (0009) created option_eod_snapshot with a "narrow"
schema (one row per CE/PE with option_type column).  The ORM models use a
"wide" schema (one row per strike, ce_oi / pe_oi / ce_ltp / pe_ltp …).
The other three tables also had minor column-name mismatches.

This migration drops all four tables and recreates them with the exact
columns the models define.

Revision ID: 0010_fix_options_tables
Revises: 0009_options_tables
Create Date: 2026-10-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010_fix_options_tables"
down_revision = "0009_options_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── drop tables created by 0009 with wrong columns ────────────────────
    op.drop_table("option_guidance_log")
    op.drop_table("option_daily_summary")
    op.drop_table("option_eod_snapshot")
    op.drop_table("option_instrument_master")

    # ── option_instrument_master ──────────────────────────────────────────
    op.create_table(
        "option_instrument_master",
        sa.Column("id",          sa.Integer,    primary_key=True, autoincrement=True),
        sa.Column("token",       sa.String,     nullable=False, unique=True),
        sa.Column("symbol",      sa.String,     nullable=False),
        sa.Column("name",        sa.String,     nullable=True),
        sa.Column("strike",      sa.Integer,    nullable=False),
        sa.Column("expiry",      sa.Date,       nullable=False),
        sa.Column("option_type", sa.String(2),  nullable=False),  # CE / PE
        sa.Column("lot_size",    sa.Integer,    nullable=False),
        sa.Column("fetched_at",  sa.DateTime,   nullable=True),
    )
    op.create_index(
        "ix_option_master_token",
        "option_instrument_master", ["token"], unique=True
    )
    op.create_index(
        "ix_option_master_expiry_strike",
        "option_instrument_master", ["expiry", "strike", "option_type"]
    )

    # ── option_eod_snapshot  (wide: one row per strike, not per side) ─────
    op.create_table(
        "option_eod_snapshot",
        sa.Column("id",        sa.Integer,          primary_key=True, autoincrement=True),
        sa.Column("date",      sa.Date,             nullable=False),
        sa.Column("expiry",    sa.Date,             nullable=False),
        sa.Column("strike",    sa.Integer,          nullable=False),
        sa.Column("ce_oi",     sa.BigInteger,       nullable=True),
        sa.Column("pe_oi",     sa.BigInteger,       nullable=True),
        sa.Column("ce_ltp",    sa.Numeric(12, 2),   nullable=True),
        sa.Column("pe_ltp",    sa.Numeric(12, 2),   nullable=True),
        sa.Column("ce_volume", sa.BigInteger,       nullable=True),
        sa.Column("pe_volume", sa.BigInteger,       nullable=True),
        sa.Column("created_at", sa.DateTime,        nullable=True),
    )
    op.create_index(
        "ix_option_eod_date",
        "option_eod_snapshot", ["date"]
    )
    op.create_unique_constraint(
        "uq_option_eod_date_expiry_strike",
        "option_eod_snapshot",
        ["date", "expiry", "strike"],
    )

    # ── option_daily_summary ──────────────────────────────────────────────
    op.create_table(
        "option_daily_summary",
        sa.Column("id",                  sa.Integer,         primary_key=True, autoincrement=True),
        sa.Column("date",                sa.Date,            nullable=False),
        sa.Column("expiry",              sa.Date,            nullable=False),
        sa.Column("spot_close",          sa.Numeric(10, 2),  nullable=True),
        sa.Column("pcr",                 sa.Numeric(6, 3),   nullable=True),
        sa.Column("max_pain",            sa.Integer,         nullable=True),
        sa.Column("atm_iv",              sa.Numeric(6, 2),   nullable=True),
        sa.Column("iv_skew",             sa.Numeric(6, 2),   nullable=True),
        sa.Column("expected_move_range", sa.Numeric(8, 2),   nullable=True),
        sa.Column("created_at",          sa.DateTime,        nullable=True),
    )
    op.create_unique_constraint(
        "uq_option_daily_summary_date",
        "option_daily_summary",
        ["date"],
    )

    # ── option_guidance_log ───────────────────────────────────────────────
    op.create_table(
        "option_guidance_log",
        sa.Column("id",                     sa.Integer,         primary_key=True, autoincrement=True),
        sa.Column("logged_at",              sa.DateTime,        nullable=False),
        sa.Column("expiry",                 sa.Date,            nullable=True),
        sa.Column("spot",                   sa.Numeric(10, 2),  nullable=True),
        sa.Column("score",                  sa.Integer,         nullable=True),
        sa.Column("bias",                   sa.String(20),      nullable=True),
        sa.Column("confidence",             sa.Integer,         nullable=True),
        sa.Column("top_opportunity_strike", sa.Integer,         nullable=True),
        sa.Column("top_opportunity_type",   sa.String(20),      nullable=True),
        sa.Column("signal_breakdown",       JSONB,              nullable=True),
        sa.Column("created_at",             sa.DateTime,        nullable=True),
    )
    op.create_index(
        "ix_option_guidance_logged_at",
        "option_guidance_log", ["logged_at"]
    )


def downgrade() -> None:
    op.drop_table("option_guidance_log")
    op.drop_table("option_daily_summary")
    op.drop_table("option_eod_snapshot")
    op.drop_table("option_instrument_master")
