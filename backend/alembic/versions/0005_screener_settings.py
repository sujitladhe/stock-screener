"""screener_settings table — stores user-configurable screener conditions.

Replaces the hardcoded multiplier / value constants in live_engine.py
with a single DB row so they can be updated via the Settings page
without redeploying code.

Revision ID: 0005_screener_settings
Revises: 0004_new_features
Create Date: 2026-10-14
"""
from alembic import op
import sqlalchemy as sa


revision = "0005_screener_settings"
down_revision = "0004_new_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "screener_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # Condition 1: volume > cond1_multiplier × avg  AND  value > cond1_min_value_cr Cr
        sa.Column("cond1_multiplier", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("cond1_min_value_cr", sa.Numeric(), nullable=False, server_default="4"),
        # Condition 2: volume > cond2_multiplier × avg  AND  value > cond2_min_value_cr Cr
        sa.Column("cond2_multiplier", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("cond2_min_value_cr", sa.Numeric(), nullable=False, server_default="6"),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("screener_settings")
