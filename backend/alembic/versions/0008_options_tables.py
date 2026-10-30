"""options tables

Revision ID: 0008_options_tables
Revises: 0007_candle_sync_tracking
Create Date: 2026-10-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0008_options_tables'
down_revision = '0007_candle_sync_tracking'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Instrument master — token↔strike↔expiry map, refreshed daily
    op.create_table(
        'option_instrument_master',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('symbol', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('strike', sa.Integer(), nullable=False),
        sa.Column('expiry', sa.Date(), nullable=False),
        sa.Column('option_type', sa.String(2), nullable=False),  # CE or PE
        sa.Column('lot_size', sa.Integer(), nullable=False),
        sa.Column('fetched_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token', name='uq_option_master_token'),
    )
    op.create_index('ix_option_master_expiry_strike', 'option_instrument_master',
                    ['expiry', 'strike', 'option_type'])

    # 2. EOD OI snapshot — strike-level data saved at market close each day
    op.create_table(
        'option_eod_snapshot',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('expiry', sa.Date(), nullable=False),
        sa.Column('strike', sa.Integer(), nullable=False),
        sa.Column('ce_oi', sa.BigInteger(), nullable=True),
        sa.Column('pe_oi', sa.BigInteger(), nullable=True),
        sa.Column('ce_ltp', sa.Numeric(12, 2), nullable=True),
        sa.Column('pe_ltp', sa.Numeric(12, 2), nullable=True),
        sa.Column('ce_volume', sa.BigInteger(), nullable=True),
        sa.Column('pe_volume', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('date', 'expiry', 'strike',
                            name='uq_option_eod_date_expiry_strike'),
    )
    op.create_index('ix_option_eod_date', 'option_eod_snapshot', ['date'])

    # 3. Daily summary — PCR, max pain, IV at close (for backtesting)
    op.create_table(
        'option_daily_summary',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('expiry', sa.Date(), nullable=False),
        sa.Column('spot_close', sa.Numeric(10, 2), nullable=True),
        sa.Column('pcr', sa.Numeric(6, 3), nullable=True),
        sa.Column('max_pain', sa.Integer(), nullable=True),
        sa.Column('atm_iv', sa.Numeric(6, 2), nullable=True),
        sa.Column('iv_skew', sa.Numeric(6, 2), nullable=True),
        sa.Column('expected_move_range', sa.Numeric(8, 2), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('date', name='uq_option_daily_summary_date'),
    )

    # 4. Guidance engine log — hourly snapshots (for backtesting the engine)
    op.create_table(
        'option_guidance_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('logged_at', sa.DateTime(), nullable=False),
        sa.Column('expiry', sa.Date(), nullable=True),
        sa.Column('spot', sa.Numeric(10, 2), nullable=True),
        sa.Column('score', sa.Integer(), nullable=True),
        sa.Column('bias', sa.String(20), nullable=True),
        sa.Column('confidence', sa.Integer(), nullable=True),
        sa.Column('top_opportunity_strike', sa.Integer(), nullable=True),
        sa.Column('top_opportunity_type', sa.String(20), nullable=True),
        sa.Column('signal_breakdown', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_option_guidance_logged_at', 'option_guidance_log',
                    ['logged_at'])


def downgrade():
    op.drop_index('ix_option_guidance_logged_at', table_name='option_guidance_log')
    op.drop_table('option_guidance_log')
    op.drop_table('option_daily_summary')
    op.drop_index('ix_option_eod_date', table_name='option_eod_snapshot')
    op.drop_table('option_eod_snapshot')
    op.drop_index('ix_option_master_expiry_strike',
                  table_name='option_instrument_master')
    op.drop_table('option_instrument_master')
