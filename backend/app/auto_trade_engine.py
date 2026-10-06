"""
auto_trade_engine.py — pure decision logic for AUTO TRADE orders
(requirement 10). No network, no database, no asyncio: like
live_engine.py and alert_engine.py, kept pure so it can be unit tested
with synthetic ticks before it ever drives a real order.

New in 0004:
  AutoOrderState.day_high_pct_limit — optional upper cap on the stock's
    intraday % gain. If the stock is already up >= this % for the day when
    the engine evaluates the order, evaluation is skipped and the order stays
    Active. Once the stock pulls back below the cap (or if it never reached
    it), evaluation resumes normally. This is a LIVE check, not a one-time
    gate: the order can still fire later in the same session if the condition
    becomes true and the stock's gain has fallen back under the cap.

  evaluate_auto_order now accepts prev_close (keyword-only) so the day-high
    check can be computed. Callers that don't have prev_close simply omit the
    argument; the check is then skipped silently (not a bug — prev_close is
    always available from StockState.prev_close in practice).
"""

from dataclasses import dataclass
from datetime import datetime, time as dtime
from typing import Optional

MARKET_OPEN = dtime(9, 15, 0)
MARKET_CLOSE = dtime(15, 30, 0)

ONE_CRORE = 10_000_000

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

    volume_threshold: Optional[float] = None
    candle_pct_threshold: Optional[float] = None
    combinator: Optional[str] = None
    valid_till: Optional[dtime] = None

    # NEW (0004): if set, the order won't fire while the stock's intraday
    # gain (ltp vs prev_close) is >= this value. It can still fire once the
    # stock pulls back below the limit.
    day_high_pct_limit: Optional[float] = None


@dataclass
class CandleState:
    """Tracks the CURRENT 1-minute candle of one stock, built from ticks."""
    minute: Optional[datetime] = None
    open_price: Optional[float] = None
    observed_from_start: bool = False


@dataclass
class AutoTriggerResult:
    """What evaluate_auto_order returns when an order should fire."""
    volume_value: float
    candle_pct: Optional[float]
    details: str


def update_candle(
    candle: CandleState,
    tick_minute: datetime,
    ltp: float,
    is_first_tick_of_day: bool = False,
) -> None:
    if candle.minute is None:
        candle.minute = tick_minute
        candle.open_price = ltp
        candle.observed_from_start = is_first_tick_of_day
    elif tick_minute > candle.minute:
        candle.minute = tick_minute
        candle.open_price = ltp
        candle.observed_from_start = True


def is_within_trading_window(now: datetime, valid_till: Optional[dtime]) -> bool:
    if now.weekday() >= 5:
        return False
    t = now.time()
    if t < MARKET_OPEN or t >= MARKET_CLOSE:
        return False
    if valid_till is not None:
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
    prev_close: Optional[float] = None,  # NEW (0004)
) -> Optional[AutoTriggerResult]:
    """
    Decides whether one auto order should fire on the tick just processed.
    Returns AutoTriggerResult if so, else None. Never raises — returns None
    on any invalid/missing data so the tick loop is never disrupted.
    """
    if tick_time.date() != now.date():
        return None

    if not is_within_trading_window(now, order.valid_till):
        return None

    if not candle.observed_from_start:
        return None
    if candle.open_price is None or candle.open_price <= 0:
        return None
    if current_minute_volume < 0 or ltp <= 0:
        return None

    if order.volume_threshold is None and order.candle_pct_threshold is None:
        return None

    # NEW (0004) — day-high cap check. If the stock is already up >= the limit
    # for the day, skip this tick. We'll try again on the next tick — the order
    # stays Active; this is not a one-time check.
    if order.day_high_pct_limit is not None and prev_close is not None and prev_close > 0:
        day_change_pct = (ltp - prev_close) / prev_close * 100
        if day_change_pct >= order.day_high_pct_limit:
            return None

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
