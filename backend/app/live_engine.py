"""
live_engine.py — the core decision logic for the live screener.

KEY DESIGN FACT (confirmed via a real test capture, not assumed):
Ventura's tick "volume" field is a CUMULATIVE running total for the
whole trading day, not a per-trade quantity. So we do NOT sum
individual trades ourselves — we track "what was the cumulative total
at the start of this minute" and subtract, on every tick:

    current_minute_volume = latest_cumulative_volume - volume_at_minute_start

This module is deliberately pure/synchronous and has NO network code —
it's built this way specifically so the decision logic can be unit
tested with synthetic tick sequences (see scripts/test_live_engine.py)
before it's ever wired to a real, hard-to-reproduce live feed.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional


# Your confirmed screener conditions:
#   20x average AND value > 4 Cr, OR 10x average AND value > 6 Cr
CONDITION_1_MULTIPLIER = 20
CONDITION_1_MIN_VALUE = 4_00_00_000  # 4 Cr
CONDITION_2_MULTIPLIER = 10
CONDITION_2_MIN_VALUE = 6_00_00_000  # 6 Cr

TICK_TIMESTAMP_FORMAT = "%d/%m/%Y %H:%M:%S"


@dataclass
class StockState:
    """Live in-memory state for one stock. One of these per subscribed stock, held in a plain dict keyed by exchange_token."""
    exchange_token: str
    trading_symbol: str
    avg_volume_per_min: Decimal

    current_minute: Optional[datetime] = None
    volume_at_minute_start: Optional[int] = None
    latest_volume: Optional[int] = None
    ltp: Optional[float] = None
    prev_close: Optional[float] = None

    # Prevents re-alerting multiple times within the same minute once
    # the condition has already fired once (confirmed requirement).
    last_alerted_minute: Optional[datetime] = None


@dataclass
class Tick:
    """A parsed tick, independent of Ventura's raw array format."""
    exchange_token: str
    ltp: float
    prev_close: float
    volume: int
    timestamp: datetime


@dataclass
class AlertEvent:
    """
    What gets produced when a stock's condition is satisfied.

    minute: the truncated (seconds=0) minute bucket — used ONLY for
    internal dedup logic (has this stock already alerted this minute).
    triggered_at: the REAL tick timestamp (actual seconds included) —
    used for anything shown to a person or stored as "when did this
    actually happen." These were conflated in an earlier version,
    which caused every displayed timestamp to show :00 seconds
    regardless of when the alert genuinely fired.
    """
    exchange_token: str
    trading_symbol: str
    minute: datetime
    triggered_at: datetime
    current_minute_volume: int
    avg_volume_per_min: Decimal
    multiple: float
    value: float
    ltp: float
    prev_close: float  # previous day's close — used to compute % change on the frontend
    condition_matched: str  # "20x_4cr" or "10x_6cr"


def parse_tick(raw_message: list) -> Optional[Tick]:
    """
    Parses one of Ventura's raw WebSocket tick arrays. Returns None for
    message shapes we don't recognize (e.g. a future message type)
    rather than raising, so one unexpected message doesn't crash the
    whole engine.

    Confirmed real format (from a live test capture):
        ["nse:ltp", exchange_token, ltp, open, high, low, close, volume, "DD/MM/YYYY HH:MM:SS"]

    Note: "close" in this feed is the PREVIOUS day's close (standard
    for a live feed), not today's — kept here since it's useful later
    for computing %-change, at no extra cost.
    """
    if not isinstance(raw_message, list) or len(raw_message) < 9:
        return None
    if not str(raw_message[0]).endswith(":ltp"):
        return None  # not a plain LTP tick (e.g. could be a depth message if we ever subscribe to that too)

    try:
        return Tick(
            exchange_token=str(raw_message[1]),
            ltp=float(raw_message[2]),
            prev_close=float(raw_message[6]),
            volume=int(raw_message[7]),
            timestamp=datetime.strptime(raw_message[8], TICK_TIMESTAMP_FORMAT),
        )
    except (ValueError, IndexError, TypeError):
        return None


def process_tick(state: StockState, tick: Tick, is_first_tick_of_day: bool = False) -> Optional[AlertEvent]:
    """
    Updates a stock's state with a new tick and returns an AlertEvent
    if a screener condition is newly satisfied this minute, else None.

    is_first_tick_of_day: pass True only when this is genuinely the
    first tick received for this stock since market open (e.g. engine
    started before 9:16 AM and this is the very first message for this
    token). In that case, the minute's baseline is 0, so any volume
    from the opening auction correctly counts toward the first minute.
    If the engine reconnects MID-DAY instead, this should be False —
    otherwise we'd wrongly treat the stock's entire day-so-far volume
    as "this minute" and fire a false, massive alert. This distinction
    matters and should not be defaulted casually — see the reconnect
    handling in ws_client.py for how it's determined in practice.
    """
    minute = tick.timestamp.replace(second=0, microsecond=0)

    if state.current_minute is None:
        # First tick we've ever seen for this stock in this run.
        state.volume_at_minute_start = 0 if is_first_tick_of_day else tick.volume
        state.current_minute = minute
    elif minute != state.current_minute:
        # A new minute has begun — the baseline for "this minute" is
        # whatever the cumulative total was right before it started.
        state.volume_at_minute_start = state.latest_volume
        state.current_minute = minute

    state.latest_volume = tick.volume
    state.ltp = tick.ltp
    state.prev_close = tick.prev_close

    current_minute_volume = state.latest_volume - state.volume_at_minute_start

    if current_minute_volume < 0:
        # Shouldn't happen (cumulative volume shouldn't go backwards
        # within a day) — could indicate a data glitch or an
        # unexpected day-rollover. Don't alert on garbage data; just
        # resync the baseline so we recover cleanly on the next tick.
        state.volume_at_minute_start = state.latest_volume
        return None

    value = current_minute_volume * state.ltp
    avg = float(state.avg_volume_per_min)

    condition_matched = None
    multiple = current_minute_volume / avg if avg > 0 else 0

    if current_minute_volume > CONDITION_1_MULTIPLIER * avg and value > CONDITION_1_MIN_VALUE:
        condition_matched = "20x_4cr"
    elif current_minute_volume > CONDITION_2_MULTIPLIER * avg and value > CONDITION_2_MIN_VALUE:
        condition_matched = "10x_6cr"

    if condition_matched and state.last_alerted_minute != minute:
        state.last_alerted_minute = minute
        return AlertEvent(
            exchange_token=state.exchange_token,
            trading_symbol=state.trading_symbol,
            minute=minute,
            triggered_at=tick.timestamp,  # real timestamp, seconds included — this is what should be displayed
            current_minute_volume=current_minute_volume,
            avg_volume_per_min=state.avg_volume_per_min,
            multiple=round(multiple, 2),
            value=round(value, 2),
            ltp=state.ltp,
            prev_close=state.prev_close,
            condition_matched=condition_matched,
        )

    return None
