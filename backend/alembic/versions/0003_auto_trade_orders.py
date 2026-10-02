"""auto trade: extra columns on orders

Requirement 10 (auto trade). An auto order is stored in the existing
`orders` table (source = 'auto') instead of a new table, so the Orders
page, cancel flow and broker-status sync all keep working off one list.

New columns:
  source                      'manual' (default, backfilled for every
                              existing row via the server default) or 'auto'
  auto_volume_threshold       volume value (volume x price) to reach, RAW RUPEES
  auto_candle_pct_threshold   current 1-min green-candle % to reach
  auto_combinator             'AND' / 'OR' when both thresholds are set
  auto_valid_till             IST time of day after which it won't trigger
  triggered_at                when the condition matched (IST, naive)
  trigger_details             text snapshot of the numbers that fired it

Apply with:  alembic upgrade head

Revision ID: 0003_auto_trade_orders
Revises: 0002_ventura_token_refreshed_date
Create Date: 2026-09-20

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0003_auto_trade_orders"
down_revision = "0002_ventura_token_refreshed_date"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
    )
    op.add_column("orders", sa.Column("auto_volume_threshold", sa.Numeric(), nullable=True))
    op.add_column("orders", sa.Column("auto_candle_pct_threshold", sa.Numeric(), nullable=True))
    op.add_column("orders", sa.Column("auto_combinator", sa.String(), nullable=True))
    op.add_column("orders", sa.Column("auto_valid_till", sa.Time(), nullable=True))
    op.add_column("orders", sa.Column("triggered_at", sa.DateTime(), nullable=True))
    op.add_column("orders", sa.Column("trigger_details", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "trigger_details")
    op.drop_column("orders", "triggered_at")
    op.drop_column("orders", "auto_valid_till")
    op.drop_column("orders", "auto_combinator")
    op.drop_column("orders", "auto_candle_pct_threshold")
    op.drop_column("orders", "auto_volume_threshold")
    op.drop_column("orders", "source")
