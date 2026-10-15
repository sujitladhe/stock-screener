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

Screener conditions are now configurable via the Settings page
(stored in screener_settings DB table). The DEFAULT_CONDITIONS
constants below serve as fallbacks when no DB row exists.
Pass a ScreenerConditions instance to process_tick() to override.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional


# ---------------------------------------------------------------------------
# Default screener conditions (used when DB has no settings row yet).
# ---------------------------------------------------------------------------
DEFAULT_COND1_MULTIPLIER = 20
DEFAULT_COND1_MIN_VALUE  = 4_00_00_000   # 4 Cr
DEFAULT_COND2_MULTIPLIER = 10
DEFAULT_COND2_MIN_VALUE  = 6_00_00_000   # 6 Cr

TICK_TIMESTAMP_FORMAT = "%d/%m/%Y %H:%M:%S"

ONE_CR = 1_00_00_000


@dataclass
class ScreenerConditions:
    """
    Holds the two screener conditions in raw rupees.
    Loaded from screener_settings DB table at engine startup and refreshed
    every 2 minutes. Falls back to the DEFAULT_* constants above when the
    DB table is empty.
    """
    cond1_multiplier: int = DEFAULT_COND1_MULTIPLIER
    cond1_min_value: int  = DEFAULT_COND1_MIN_VALUE
    cond2_multiplier: int = DEFAULT_COND2_MULTIPLIER
    cond2_min_value: int  = DEFAULT_COND2_MIN_VALUE


@dataclass
class StockState:
    """Live in-memory state for one stock."""
    exchange_token: str
    trading_symbol: str
    avg_volume_per_min: Decimal

    current_minute: Optional[datetime] = None
    volume_at_minute_start: Optional[int] = None
    latest_volume: Optional[int] = None
    ltp: Optional[float] = None
    prev_close: Optional[float] = None

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
    internal dedup logic.
    triggered_at: the REAL tick timestamp (actual seconds included) —
    used for anything shown to a person or stored.
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
    prev_close: float
    condition_matched: str  # e.g. "20x_4cr", "10x_6cr", or dynamic values


def _cr_label(rupees: int) -> str:
    """Formats a rupee value as a Crore label, e.g. 40000000 → '4cr'."""
    cr = rupees / ONE_CR
    # :g strips trailing zeros: 4.0 → "4", 4.5 → "4.5"
    return f"{cr:g}cr"


def parse_tick(raw_message: list) -> Optional[Tick]:
    """
    Parses one of Ventura's raw WebSocket tick arrays.
    Returns None for unrecognised shapes rather than raising.

    Confirmed real format:
        ["nse:ltp", exchange_token, ltp, open, high, low, close, volume, "DD/MM/YYYY HH:MM:SS"]
    """
    if not isinstance(raw_message, list) or len(raw_message) < 9:
        return None
    if not str(raw_message[0]).endswith(":ltp"):
        return None

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


def process_tick(
    state: StockState,
    tick: Tick,
    is_first_tick_of_day: bool = False,
    conditions: Optional[ScreenerConditions] = None,
) -> Optional[AlertEvent]:
    """
    Updates a stock's state with a new tick and returns an AlertEvent
    if a screener condition is newly satisfied this minute, else None.

    conditions: pass a ScreenerConditions instance to use live DB values.
                If None, falls back to the DEFAULT_* module constants.
    """
    cond = conditions if conditions is not None else ScreenerConditions()

    minute = tick.timestamp.replace(second=0, microsecond=0)

    if state.current_minute is None:
        state.volume_at_minute_start = 0 if is_first_tick_of_day else tick.volume
        state.current_minute = minute
    elif minute != state.current_minute:
        state.volume_at_minute_start = state.latest_volume
        state.current_minute = minute

    state.latest_volume = tick.volume
    state.ltp = tick.ltp
    state.prev_close = tick.prev_close

    current_minute_volume = state.latest_volume - state.volume_at_minute_start

    if current_minute_volume < 0:
        state.volume_at_minute_start = state.latest_volume
        return None

    value = current_minute_volume * state.ltp
    avg = float(state.avg_volume_per_min)
    multiple = current_minute_volume / avg if avg > 0 else 0

    condition_matched = None

    if current_minute_volume > cond.cond1_multiplier * avg and value > cond.cond1_min_value:
        condition_matched = f"{cond.cond1_multiplier}x_{_cr_label(cond.cond1_min_value)}"
    elif current_minute_volume > cond.cond2_multiplier * avg and value > cond.cond2_min_value:
        condition_matched = f"{cond.cond2_multiplier}x_{_cr_label(cond.cond2_min_value)}"

    if condition_matched and state.last_alerted_minute != minute:
        state.last_alerted_minute = minute
        return AlertEvent(
            exchange_token=state.exchange_token,
            trading_symbol=state.trading_symbol,
            minute=minute,
            triggered_at=tick.timestamp,
            current_minute_volume=current_minute_volume,
            avg_volume_per_min=state.avg_volume_per_min,
            multiple=round(multiple, 2),
            value=round(value, 2),
            ltp=state.ltp,
            prev_close=state.prev_close,
            condition_matched=condition_matched,
        )

    return None
