"""
models.py — SQLAlchemy table definitions.

UserSession covers login/session management.
Instrument is the shared NSE equity master list (common across all
users, per the architecture doc). We'll add VolumeAverage, Watchlist,
ScreenerCondition, etc. as we build those phases — deliberately not
creating empty placeholder tables for features we haven't built yet.

TIMESTAMP CONVENTION: per this project's own IST-discipline principle
(see Section 3 of the handoff doc — "timezone bugs are a recurring
risk"), every wall-clock timestamp a person will actually SEE (order
placement time, alert trigger time, etc.) is stored as a naive
datetime that VALUES Indian time, not UTC — matching how
live_engine.py's tick.timestamp is already handled (parsed directly
from Ventura's IST-valued feed, stored naive). now_ist_naive() below
is the one helper for producing these; nothing in this file should use
bare datetime.utcnow() for a timestamp a person will read. Purely
internal bookkeeping fields (created_at housekeeping, session
last-active tracking) are lower-stakes and left as UTC where they
already were, to avoid touching more than this fix needs.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import Column, String, DateTime, Boolean, Integer, Numeric, UniqueConstraint, Date
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.database import Base

IST = ZoneInfo("Asia/Kolkata")


def now_ist_naive() -> datetime:
    """
    Current Indian wall-clock time, as a naive datetime (no tzinfo) —
    matching the convention already used for tick.timestamp elsewhere
    in this app. Use this for any stored timestamp a person will see
    displayed (order placed_at, status-check times, etc.).
    """
    return datetime.now(IST).replace(tzinfo=None)


class UserSession(Base):
    """
    One row per logged-in browser session. A user's Ventura client_id
    is effectively their identity in this app (no separate
    signup/password system, since it's just you and a few friends who
    already have their own Ventura API access).

    Credentials needed to auto-relogin when the Ventura auth_token
    expires are stored encrypted (see app/security.py) — never in
    plaintext.
    """
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

    # The IST calendar date (not a timestamp) the Ventura auth_token
    # was last (re)obtained on. Ventura's own docs don't state
    # explicitly whether a token obtained on one trading day is
    # expected to work on the next, and a real relogin failure was
    # observed after a token sat unused for a while — so rather than
    # trust ventura_auth_expiry alone, get_current_session also forces
    # a fresh login whenever this date isn't today's IST date, however
    # far off auth_expiry still claims to be. Nullable so existing
    # rows (from before this column existed) just trigger one relogin
    # the next time they're used, rather than needing a backfill.
    ventura_token_refreshed_date = Column(Date, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active_at = Column(DateTime, default=datetime.utcnow)


class Instrument(Base):
    """
    The shared NSE equity instrument master list — same data for every
    user of the app, refreshed daily from Ventura's instruments file.

    We only store NSE + instrument type 'EQ' rows here (mainboard
    equity) — NFO/BFO options & futures, SME (SM/ST), trade-to-trade
    (BE/BZ), InvITs (IV), and REITs (RR) are filtered out at import
    time, not stored and filtered later, since they're a different
    universe from what the screener is meant to scan.

    is_active tracks whether this instrument appeared in the most
    recent daily pull — if a stock gets delisted, we mark it inactive
    rather than deleting the row, so historical screener/order data
    that references it doesn't break.
    """
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

    # Angel One's own symboltoken for this stock — a completely
    # separate numbering system from Ventura's exchange_token, needed
    # because historical candles come from Angel, not Ventura. Null
    # until the mapping step successfully matches it; stocks that
    # can't be matched should be flagged, not silently skipped.
    angel_symbol_token = Column(String, nullable=True)


class AngelSession(Base):
    """
    A single shared Angel One login session, used only by backend jobs
    (the historical data puller) — NOT tied to any individual app user.
    Angel One is used purely as a shared data source here; only Ventura
    handles per-user login/trading.

    There's only ever one meaningful row in this table (id=1) — we
    treat it as a singleton rather than creating a full session-history
    table, since we only ever care about "what's the current valid
    token."

    Angel One's loginByPassword response does NOT include an expiry
    timestamp (confirmed against a real response — unlike Ventura,
    which gives auth_expiry/refresh_expiry). Forum reports on when
    tokens actually expire are inconsistent, so instead of trusting a
    guessed expiry, angel_client.py re-logs-in whenever a request comes
    back unauthorized, and this table just tracks the latest known
    tokens for reuse between requests.
    """
    __tablename__ = "angel_session"

    id = Column(Integer, primary_key=True, autoincrement=True)
    jwt_token = Column(String, nullable=True)
    refresh_token = Column(String, nullable=True)
    feed_token = Column(String, nullable=True)
    logged_in_at = Column(DateTime, nullable=True)


class VolumeAverage(Base):
    """
    The per-stock average 1-minute volume, computed nightly from 30
    days of Angel One daily candles: (sum of volume / days_used) / 375.

    This is the shared lookup table the live tick engine will load
    into memory at market open — one row per stock, so comparisons
    during live trading are a fast in-memory check, not a DB query per
    tick (per the architecture doc's explicit requirement).

    trading_days_used matters for recently listed stocks: per your
    instruction, we don't wait for a minimum history — we use whatever
    days are available and divide by that actual count, not a fixed
    30. This field lets the screener/UI flag "thin history" stocks
    later if desired.
    """
    __tablename__ = "volume_averages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    instrument_id = Column(Integer, nullable=False, unique=True, index=True)
    avg_volume_per_min = Column(Numeric, nullable=False)
    trading_days_used = Column(Integer, nullable=False)
    total_volume_used = Column(Numeric, nullable=False)
    last_computed_at = Column(DateTime, default=datetime.utcnow)


class ScreenerDailyStat(Base):
    """
    ONE row per stock per trading day — not one row per trigger. Every
    time a stock's screener condition fires again on the same day, we
    increment occurrence_count and update the "last" snapshot fields,
    rather than inserting a new row. This keeps the table's size
    bounded by (stocks x trading days), not (stocks x every trigger),
    which matters since an actively spiking stock could otherwise
    trigger dozens of times in one session.

    This directly matches the architecture doc's requirement: "save
    the screened stock with the number of appearance in screener for
    that day" — occurrence_count IS that number, maintained directly
    rather than computed by counting event rows (which is what the
    previous version of this table did, before this redesign).

    A (instrument_id, trade_date) row is looked up and updated
    in-place on every trigger — see ws_client.py's save_alert().
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

    # Snapshot of the MOST RECENT trigger's numbers — enough for the
    # screener view to show "how it currently looks," without needing
    # a full history of every past trigger that day.
    last_current_minute_volume = Column(Integer, nullable=False)
    last_avg_volume_per_min = Column(Numeric, nullable=False)
    last_multiple = Column(Numeric, nullable=False)
    last_value = Column(Numeric, nullable=False)
    last_ltp = Column(Numeric, nullable=False)
    last_prev_close = Column(Numeric, nullable=True)  # nullable: rows written before this column existed won't have it
    last_condition_matched = Column(String, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Watchlist(Base):
    """
    A user's own watchlist — per the architecture doc, watchlists are
    a per-user resource, NOT shared (unlike Instrument/VolumeAverage).
    Owned by client_id, the same stable per-person identifier used
    throughout auth — not session_token, which changes on every login.

    A user can have multiple watchlists, each with its own color —
    per an explicit product decision, coloring moved from a per-stock
    "leg" concept to a per-WATCHLIST color applied to all its stocks
    (the leg system was removed entirely, see WatchlistStock below).
    """
    __tablename__ = "watchlists"
    __table_args__ = (
        UniqueConstraint("client_id", "name", name="uq_client_watchlist_name"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    color = Column(String, nullable=False, default="#5b8cff")  # hex color, chosen at creation
    created_at = Column(DateTime, default=datetime.utcnow)


class WatchlistStock(Base):
    """
    One stock inside one watchlist.

    IMPORTANT — a stock may belong to only ONE watchlist per user at a
    time (an explicit product decision, replacing the earlier "leg"
    system entirely). Adding a stock to a new watchlist automatically
    removes it from whichever other watchlist it was previously in —
    enforced at the application layer in routers/watchlist.py, AND at
    the database layer via the unique constraint on
    (client_id, instrument_id) below, as a safety net against bugs or
    concurrent requests racing each other.

    client_id is denormalized here (also derivable via watchlist_id ->
    Watchlist.client_id) specifically to make that uniqueness
    constraint and the "does this user already have this stock
    somewhere" lookup a simple indexed query, not a join.
    """
    __tablename__ = "watchlist_stocks"
    __table_args__ = (
        UniqueConstraint("client_id", "instrument_id", name="uq_client_instrument_single_watchlist"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    watchlist_id = Column(Integer, nullable=False, index=True)
    client_id = Column(String, nullable=False, index=True)
    instrument_id = Column(Integer, nullable=False, index=True)
    trading_symbol = Column(String, nullable=False)  # denormalized — avoids a join for the common "get my stock colors" lookup
    added_at = Column(DateTime, default=datetime.utcnow)


class Order(Base):
    """
    An order the CURRENT user placed through their OWN Ventura account
    (never the shared service account used for instruments/historical
    data — that distinction matters a lot here, since this represents
    real money movement).

    We persist orders ourselves because Ventura's Order Book API only
    retains the CURRENT DAY's orders (confirmed in their docs) — for
    "show all my past orders" (requirement 6c) beyond today, our own
    row is the only record that survives. While an order is still
    "today's," we refresh `status` by polling the broker's Order Book;
    once the day ends, status is frozen at whatever was last known,
    since the broker stops telling us more.

    placed_at/last_status_check_at store IST (see now_ist_naive above)
    — these were originally UTC (datetime.utcnow), which is what made
    "Order Placed timing is not Indian time" a real, reported bug
    rather than just a display quirk. Fixed here at the source.
    """
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String, nullable=False, index=True)

    instrument_id = Column(Integer, nullable=False)
    trading_symbol = Column(String, nullable=False)
    exchange = Column(String, nullable=False, default="NSE")

    order_kind = Column(String, nullable=False)  # "delivery" or "intraday" — determines which Ventura endpoint was called
    transaction_type = Column(String, nullable=False)  # "B" or "S", per Ventura's own codes
    order_type = Column(String, nullable=False)  # "MKT", "LMT", "SL", "SLM"
    product = Column(String, nullable=False)  # "C", "I", "M", "F" per Ventura's codes
    quantity = Column(Integer, nullable=False)
    price = Column(Numeric, nullable=True)
    trigger_price = Column(Numeric, nullable=True)
    validity = Column(String, nullable=False, default="DAY")

    # Recorded for audit/reference — how the quantity was derived, if
    # the stoploss-based auto-calculation (requirement 6d) was used.
    # Null if the user entered quantity manually instead.
    stoploss_percentage = Column(Numeric, nullable=True)
    stoploss_value = Column(Numeric, nullable=True)

    broker_order_no = Column(String, nullable=True, index=True)  # null if the broker rejected the submission itself
    status = Column(String, nullable=False, default="Pending")  # mirrors Ventura's own status strings (Pending/Executed/Cancelled/Rejected/...)
    broker_message = Column(String, nullable=True)  # success confirmation OR rejection reason, whichever Ventura sent

    placed_at = Column(DateTime, default=now_ist_naive)
    last_status_check_at = Column(DateTime, nullable=True)


class Alert(Base):
    """
    A user-defined alert (requirement 9) — per-user, on any stock (not
    limited to ones the screener has flagged). Up to two conditions,
    combined with a single AND/OR choice, per an explicit product
    decision (not a fully flexible condition builder).

    is_active lets a user pause an alert without deleting it. Runtime
    crossing-detection state (previous price/value) is NOT stored here
    — it lives only in memory while the engine runs (see
    alert_engine.AlertRuntimeState) and is rebuilt fresh on restart.
    """
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String, nullable=False, index=True)
    instrument_id = Column(Integer, nullable=False)
    trading_symbol = Column(String, nullable=False)

    condition_1_metric = Column(String, nullable=False)      # "price" or "value"
    condition_1_operator = Column(String, nullable=False)    # "above" or "below"
    condition_1_threshold = Column(Numeric, nullable=False)

    condition_2_metric = Column(String, nullable=True)
    condition_2_operator = Column(String, nullable=True)
    condition_2_threshold = Column(Numeric, nullable=True)
    combinator = Column(String, nullable=True)  # "AND" or "OR" — only meaningful if condition_2 is set

    sound_enabled = Column(Boolean, nullable=False, default=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AlertHistoryEntry(Base):
    """
    One row per time an alert actually fired. Kept indefinitely unless
    the user explicitly clears it (requirement 9e) — unlike the
    screener's daily-aggregate design, there's no product decision here
    to cap growth, since personal alert history is expected to be much
    lower-volume than the shared screener feed.
    """
    __tablename__ = "alert_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_id = Column(Integer, nullable=False, index=True)
    client_id = Column(String, nullable=False, index=True)
    trading_symbol = Column(String, nullable=False)
    triggered_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    price_at_trigger = Column(Numeric, nullable=False)
    value_at_trigger = Column(Numeric, nullable=False)
    condition_summary = Column(String, nullable=False)  # human-readable, e.g. "price above 100 AND value above 1000"
