"""
auto_trade_engine.py — pure decision logic for AUTO TRADE orders
(requirement 10). No network, no database, no asyncio: like
live_engine.py and alert_engine.py, it's kept pure on purpose so it can
be unit tested with synthetic ticks (scripts/test_auto_trade_engine.py)
before it ever drives a real order. It is also deliberately separate
from live_engine.py, so nothing here can affect the already-verified
screener.

WHAT AN AUTO ORDER WATCHES (per the product decision)
-----------------------------------------------------
  * volume value  = current-minute volume x LTP, compared with the
                    user's threshold with ">=" (RAW RUPEES here — the
                    "6 means 6 Cr" scaling is a frontend-only concern).
                    Same definition of "value" as the screener/alerts.
  * candle %      = (LTP - candle_open) / candle_open x 100 for the
                    CURRENT 1-minute candle, compared with ">=".
                    GREEN ONLY: the candle must have LTP > open. A red
                    candle never satisfies the candle condition, no
                    matter how large its % move or whether the volume
                    condition is met.
  * Either condition alone, or both combined with AND / OR.

  This is a LEVEL check ("is the condition true right now"), not a
  crossing check like alerts — an auto order fires the first time it
  sees its condition true inside its allowed window. It is one-shot:
  the caller removes it from the registry the moment it fires.

WHEN IT MAY FIRE
----------------
  * Only on trading weekdays, from 09:15:00 until 15:30:00 IST.
    (Holidays are handled outside: the engine simply isn't running.)
  * If the user set "valid till HH:MM" (minutes only, no seconds), the
    order stays valid for that WHOLE minute and is held from the next
    one: "valid till 09:30" can still fire at 09:30:59, and is held
    from 09:31:00. The order is NOT cancelled after that — it simply
    stops firing for that day and is checked again the next trading
    day (see auto_trade_registry / the Orders page).
  * Only on a tick stamped with today's date (a replayed stale tick
    from a previous session must never fire an order).

DATA-QUALITY GUARD (important — this places real orders)
--------------------------------------------------------
A candle's OPEN price and the current-minute volume baseline are only
trustworthy if we watched this stock from the START of the minute. If
the engine (re)connected in the middle of a minute, both would be
wrong (the "open" would be whatever tick happened to arrive first, and
the volume baseline could span the outage). So a minute we did not
observe from its beginning is SKIPPED for auto trade — for both
conditions — and the next full minute is used. The one exception is a
genuine pre-open startup (is_first_tick_of_day), mirroring how the
screener itself treats that case: there the day's first tick IS the
start of the minute.
"""

from dataclasses import dataclass
from datetime import datetime, time as dtime
from typing import Optional

MARKET_OPEN = dtime(9, 15, 0)
MARKET_CLOSE = dtime(15, 30, 0)

ONE_CRORE = 10_000_000

# Floating-point safety: (101.7 - 100) / 100 * 100 is 1.7000000000000028
# or 1.6999999999999886 depending on the numbers, and a user who types
# 1.7 expects "exactly 1.7%" to count. 1e-9 percent is far below
# anything meaningful in a price.
CANDLE_PCT_EPSILON = 1e-9


@dataclass
class AutoOrderState:
    """
    In-memory description of one ACTIVE auto order — just what the
    tick loop needs to decide, no DB access required per tick.
    """
    order_id: int
    client_id: str
    trading_symbol: str

    volume_threshold: Optional[float] = None       # raw rupees; None = volume condition not used
    candle_pct_threshold: Optional[float] = None   # percent;    None = candle condition not used
    combinator: Optional[str] = None               # "AND"/"OR"; only meaningful if BOTH are set
    valid_till: Optional[dtime] = None             # IST HH:MM; valid through the end of that minute; None = until market close


@dataclass
class CandleState:
    """
    Tracks the CURRENT 1-minute candle of one stock, built from ticks.

    Ventura's tick carries the DAY's open, not the minute's, so the
    minute's open is taken as the first LTP seen within that minute.
    """
    minute: Optional[datetime] = None
    open_price: Optional[float] = None
    # True only if we watched this minute from its very first tick (see
    # module docstring). Auto orders are not evaluated while False.
    observed_from_start: bool = False


@dataclass
class AutoTriggerResult:
    """What evaluate_auto_order returns when an order should fire."""
    volume_value: float
    candle_pct: Optional[float]
    details: str  # human-readable audit snapshot, stored on the order


def update_candle(
    candle: CandleState,
    tick_minute: datetime,
    ltp: float,
    is_first_tick_of_day: bool = False,
) -> None:
    """
    Feeds one tick into a stock's candle tracker. tick_minute is the
    tick's timestamp truncated to the minute (seconds=0).

    - First tick ever seen (this connection): the candle's start is
      only trusted if this is a genuine pre-open startup.
    - A LATER minute than the one being tracked: a new candle begins,
      and we saw its first tick — trusted.
    - Same minute, or an older/out-of-order minute: nothing changes
      (an old tick must never rewind the candle).
    """
    if candle.minute is None:
        candle.minute = tick_minute
        candle.open_price = ltp
        candle.observed_from_start = is_first_tick_of_day
    elif tick_minute > candle.minute:
        candle.minute = tick_minute
        candle.open_price = ltp
        candle.observed_from_start = True


def is_within_trading_window(now: datetime, valid_till: Optional[dtime]) -> bool:
    """
    now: current IST wall-clock time (aware or naive — only its
    weekday/time-of-day are used, so it MUST already be in IST).
    """
    if now.weekday() >= 5:  # Saturday / Sunday
        return False
    t = now.time()
    if t < MARKET_OPEN or t >= MARKET_CLOSE:
        return False
    if valid_till is not None:
        # "Valid till HH:MM" covers that WHOLE minute: compare at minute
        # precision, so 09:30 is still valid at 09:30:59 and the order
        # is held as soon as 09:31:00 starts.
        if t.replace(second=0, microsecond=0) > valid_till.replace(second=0, microsecond=0):
            return False
    return True


def evaluate_auto_order(
    order: AutoOrderState,
    *,
    current_minute_volume: int,
    ltp: float,
    candle: CandleState,
    tick_time: datetime,
    now: datetime,
) -> Optional[AutoTriggerResult]:
    """
    Decides whether one auto order should fire on the tick just
    processed. Returns an AutoTriggerResult if so, else None. Never
    raises for a malformed order — it returns None instead, because an
    exception here would otherwise propagate into the live tick loop.
    """
    # Never act on a tick from a previous day (e.g. a replayed snapshot).
    if tick_time.date() != now.date():
        return None

    if not is_within_trading_window(now, order.valid_till):
        return None

    # Data-quality guard: see module docstring.
    if not candle.observed_from_start:
        return None
    if candle.open_price is None or candle.open_price <= 0:
        return None
    if current_minute_volume < 0 or ltp <= 0:
        return None

    if order.volume_threshold is None and order.candle_pct_threshold is None:
        return None  # nothing to evaluate — treat as inert

    volume_value = current_minute_volume * ltp

    volume_ok: Optional[bool] = None
    if order.volume_threshold is not None:
        volume_ok = volume_value >= order.volume_threshold

    candle_pct = (ltp - candle.open_price) / candle.open_price * 100
    candle_ok: Optional[bool] = None
    if order.candle_pct_threshold is not None:
        is_green = ltp > candle.open_price
        candle_ok = is_green and (candle_pct + CANDLE_PCT_EPSILON >= order.candle_pct_threshold)

    active_checks = [c for c in (volume_ok, candle_ok) if c is not None]
    if len(active_checks) == 1:
        fired = active_checks[0]
    elif order.combinator == "OR":
        fired = any(active_checks)
    else:
        # "AND" — and also the safe default if the combinator is ever
        # missing/garbled: the stricter reading can only under-fire.
        fired = all(active_checks)

    if not fired:
        return None

    parts = []
    if order.volume_threshold is not None:
        parts.append(
            f"volume value {volume_value / ONE_CRORE:.2f} Cr "
            f"(needs {order.volume_threshold / ONE_CRORE:g} Cr)"
        )
    if order.candle_pct_threshold is not None:
        colour = "green" if ltp > candle.open_price else "red/flat"
        parts.append(
            f"{colour} candle {candle_pct:+.2f}% "
            f"(needs {order.candle_pct_threshold:g}%)"
        )
    joiner = f" {order.combinator or 'AND'} " if len(parts) > 1 else ""
    details = f"Triggered: {joiner.join(parts)} @ LTP {ltp:g}"

    return AutoTriggerResult(
        volume_value=round(volume_value, 2),
        candle_pct=round(candle_pct, 4),
        details=details,
    )
