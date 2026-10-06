"""
models.py — SQLAlchemy table definitions.

Timestamp convention: every wall-clock timestamp a person sees is stored as a
naive datetime valued in IST (use now_ist_naive()). Purely internal bookkeeping
fields use datetime.utcnow() and are left that way.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import (
    Column, String, DateTime, Boolean, Integer, Numeric,
    UniqueConstraint, Date, Time,
)
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.database import Base

IST = ZoneInfo("Asia/Kolkata")


def now_ist_naive() -> datetime:
    """Current Indian wall-clock time as a naive datetime (no tzinfo)."""
    return datetime.now(IST).replace(tzinfo=None)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_token = Column(String, unique=True, nullable=False, index=True)

    client_id = Column(String, nullable=False)
    app_key = Column(String, nullable=False)
    app_secret_encrypted = Column(String, nullable=False)
    pin_encrypted = Column(String, nullable=False)
    totp_secret_encrypted = Column(String, nullable=False)
    mac_address = Column(String, nullable=True)

    ventura_auth_token = Column(String, nullable=True)
    ventura_auth_expiry = Column(DateTime, nullable=True)
    ventura_refresh_token = Column(String, nullable=True)
    ventura_refresh_expiry = Column(DateTime, nullable=True)
    ventura_token_refreshed_date = Column(Date, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active_at = Column(DateTime, default=datetime.utcnow)


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint("exchange", "exchange_token", name="uq_exchange_token"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    exchange = Column(String, nullable=False)
    exchange_token = Column(String, nullable=False, index=True)
    trading_symbol = Column(String, nullable=False, index=True)
    name = Column(String, nullable=True)
    instrument_type = Column(String, nullable=False)
    segment = Column(String, nullable=True)
    tick_size = Column(Numeric, nullable=True)
    lot_size = Column(Integer, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_synced_at = Column(DateTime, default=datetime.utcnow)

    angel_symbol_token = Column(String, nullable=True)


class AngelSession(Base):
    __tablename__ = "angel_session"

    id = Column(Integer, primary_key=True, autoincrement=True)
    jwt_token = Column(String, nullable=True)
    refresh_token = Column(String, nullable=True)
    feed_token = Column(String, nullable=True)
    logged_in_at = Column(DateTime, nullable=True)


class VolumeAverage(Base):
    __tablename__ = "volume_averages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    instrument_id = Column(Integer, nullable=False, unique=True, index=True)
    avg_volume_per_min = Column(Numeric, nullable=False)
    trading_days_used = Column(Integer, nullable=False)
    total_volume_used = Column(Numeric, nullable=False)
    last_computed_at = Column(DateTime, default=datetime.utcnow)


class ScreenerDailyStat(Base):
    """
    ONE row per stock per trading day. Updated in-place on each trigger.
    New columns last_circuit_pct and last_candle_pct added in migration 0004.
    """
    __tablename__ = "screener_daily_stats"
    __table_args__ = (
        UniqueConstraint("instrument_id", "trade_date", name="uq_instrument_trade_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    instrument_id = Column(Integer, nullable=False, index=True)
    trading_symbol = Column(String, nullable=False, index=True)
    trade_date = Column(Date, nullable=False, index=True)

    occurrence_count = Column(Integer, nullable=False, default=1)
    first_triggered_at = Column(DateTime, nullable=False)
    last_triggered_at = Column(DateTime, nullable=False)

    last_current_minute_volume = Column(Integer, nullable=False)
    last_avg_volume_per_min = Column(Numeric, nullable=False)
    last_multiple = Column(Numeric, nullable=False)
    last_value = Column(Numeric, nullable=False)
    last_ltp = Column(Numeric, nullable=False)
    last_prev_close = Column(Numeric, nullable=True)
    last_condition_matched = Column(String, nullable=False)

    # Added in migration 0004
    last_circuit_pct = Column(Integer, nullable=True)   # e.g. 5, 10, 20
    last_candle_pct = Column(Numeric, nullable=True)    # current-minute green candle %

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Watchlist(Base):
    __tablename__ = "watchlists"
    __table_args__ = (
        UniqueConstraint("client_id", "name", name="uq_client_watchlist_name"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    color = Column(String, nullable=False, default="#5b8cff")
    created_at = Column(DateTime, default=datetime.utcnow)


class WatchlistStock(Base):
    __tablename__ = "watchlist_stocks"
    __table_args__ = (
        UniqueConstraint("client_id", "instrument_id", name="uq_client_instrument_single_watchlist"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    watchlist_id = Column(Integer, nullable=False, index=True)
    client_id = Column(String, nullable=False, index=True)
    instrument_id = Column(Integer, nullable=False, index=True)
    trading_symbol = Column(String, nullable=False)
    added_at = Column(DateTime, default=datetime.utcnow)


class Order(Base):
    """
    Manual and auto orders. New fields added in migration 0004:
      auto_expires_daily      – True = "today only" (expires at end of trading day)
      auto_day_high_pct_limit – optional % cap on intraday gain; order won't fire if stock
                                is already up this much for the day.
    """
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String, nullable=False, index=True)

    instrument_id = Column(Integer, nullable=False)
    trading_symbol = Column(String, nullable=False)
    exchange = Column(String, nullable=False, default="NSE")

    order_kind = Column(String, nullable=False)
    transaction_type = Column(String, nullable=False)
    order_type = Column(String, nullable=False)
    product = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Numeric, nullable=True)
    trigger_price = Column(Numeric, nullable=True)
    validity = Column(String, nullable=False, default="DAY")

    stoploss_percentage = Column(Numeric, nullable=True)
    stoploss_value = Column(Numeric, nullable=True)

    broker_order_no = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, default="Pending")
    broker_message = Column(String, nullable=True)

    placed_at = Column(DateTime, default=now_ist_naive)
    last_status_check_at = Column(DateTime, nullable=True)

    # --- Auto trade (0003) ---
    source = Column(String, nullable=False, default="manual", server_default="manual")
    auto_volume_threshold = Column(Numeric, nullable=True)
    auto_candle_pct_threshold = Column(Numeric, nullable=True)
    auto_combinator = Column(String, nullable=True)
    auto_valid_till = Column(Time, nullable=True)
    triggered_at = Column(DateTime, nullable=True)
    trigger_details = Column(String, nullable=True)

    # --- Auto trade (0004) ---
    # True = the order expires at the end of its first trading day (today-only).
    # False (default) = stays Active across trading days until it fires or is cancelled.
    auto_expires_daily = Column(Boolean, nullable=False, default=False, server_default="false")
    # Optional upper cap on the stock's intraday % gain. If the stock is already up
    # this much when the engine evaluates the order, it skips and waits. If the
    # stock later pulls back below the cap, it resumes checking.
    auto_day_high_pct_limit = Column(Numeric, nullable=True)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String, nullable=False, index=True)
    instrument_id = Column(Integer, nullable=False)
    trading_symbol = Column(String, nullable=False)

    condition_1_metric = Column(String, nullable=False)
    condition_1_operator = Column(String, nullable=False)
    condition_1_threshold = Column(Numeric, nullable=False)

    condition_2_metric = Column(String, nullable=True)
    condition_2_operator = Column(String, nullable=True)
    condition_2_threshold = Column(Numeric, nullable=True)
    combinator = Column(String, nullable=True)

    sound_enabled = Column(Boolean, nullable=False, default=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AlertHistoryEntry(Base):
    __tablename__ = "alert_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_id = Column(Integer, nullable=False, index=True)
    client_id = Column(String, nullable=False, index=True)
    trading_symbol = Column(String, nullable=False)
    triggered_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    price_at_trigger = Column(Numeric, nullable=False)
    value_at_trigger = Column(Numeric, nullable=False)
    condition_summary = Column(String, nullable=False)


class IgnoredStock(Base):
    """
    Per-user, per-day list of stocks hidden from the Live screener.
    A stock in this table is suppressed from the user's view even if it keeps
    meeting the screener condition. The list is purely a display filter on the
    frontend — the backend broadcasts alerts for all stocks regardless. Rows
    have no automatic expiry; a nightly job or the daily-reset logic on the
    frontend treats only today's rows as active.

    Added in migration 0004.
    """
    __tablename__ = "ignored_stocks"
    __table_args__ = (
        UniqueConstraint(
            "client_id", "trading_symbol", "trade_date",
            name="uq_ignored_client_symbol_date",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String, nullable=False, index=True)
    trading_symbol = Column(String, nullable=False)
    trade_date = Column(Date, nullable=False)
    ignored_at = Column(DateTime, default=now_ist_naive)
