"""
alert_engine.py — pure logic for user-defined alerts (requirement 9).

Deliberately independent of live_engine.py / StockState -- alerts can
be set on ANY stock (not just ones with a computed screener average),
and keeping this logic separate avoids any risk of a bug here
affecting the already-verified screener engine. The cost is some
redundant "track the previous value" bookkeeping, which is cheap given
the expected number of alerts is small.

KEY DEFINITION -- "crosses": a TRANSITION through the threshold, not
"is currently past it". If a stock is already above your threshold
when you create the alert, that is NOT a crossing -- nothing fires
until it moves back below and then above again. This matches the
literal meaning of "crosses" in the requirements doc, and avoids an
alert firing immediately and repeatedly just because a stock happens
to already be past the threshold.

Combining two conditions: both are evaluated as CROSSING EVENTS on
the SAME tick. For "AND", both metrics must cross their thresholds on
the exact same tick to fire -- a deliberately strict interpretation of
the doc's wording, worth being aware of: it's a narrower condition
than "both are currently past their thresholds," and could in
practice fire less often than some users might expect.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class AlertRuntimeState:
    """
    In-memory tracking for one active alert. One of these per alert,
    held in a dict keyed by alert_id inside ws_client.py's running
    engine -- NOT persisted; if the server restarts, crossing
    detection starts fresh (the alert won't fire spuriously on
    restart, since a fresh state has no "previous value" to compare
    against yet -- see evaluate_alert() below).
    """
    alert_id: int
    client_id: str
    trading_symbol: str

    condition_1_metric: str      # "price" or "value"
    condition_1_operator: str    # "above" or "below"
    condition_1_threshold: float

    condition_2_metric: Optional[str] = None
    condition_2_operator: Optional[str] = None
    condition_2_threshold: Optional[float] = None
    combinator: Optional[str] = None  # "AND" or "OR" -- only meaningful if condition_2 is set

    prev_price: Optional[float] = None
    prev_value: Optional[float] = None  # current-minute volume * price, same "value" concept as the screener


def _crossed(operator: str, prev: Optional[float], current: float, threshold: float) -> bool:
    """
    True only on a genuine transition through the threshold, using
    >= / <= semantics (per an explicit product decision — "crosses,
    greater than or equal to" — not strict > / <).
    prev=None means this is the first observation for this metric —
    correctly returns False, since a crossing requires a prior value
    to compare against (this is what prevents a spurious fire the
    moment an alert is created for a stock already past its threshold).
    """
    if prev is None:
        return False
    if operator == "above":
        return prev < threshold <= current
    elif operator == "below":
        return prev > threshold >= current
    else:
        raise ValueError(f"operator must be 'above' or 'below', got {operator!r}")


def evaluate_alert(state: AlertRuntimeState, current_price: float, current_value: float) -> bool:
    """
    Checks one alert against a new tick's price and current-minute
    value. Returns True if the alert should fire THIS tick. Always
    updates state's prev_price/prev_value for next time, regardless of
    whether it fired.
    """
    cond1_prev = state.prev_price if state.condition_1_metric == "price" else state.prev_value
    cond1_current = current_price if state.condition_1_metric == "price" else current_value
    cond1_fired = _crossed(state.condition_1_operator, cond1_prev, cond1_current, state.condition_1_threshold)

    result = cond1_fired

    if state.condition_2_metric:
        cond2_prev = state.prev_price if state.condition_2_metric == "price" else state.prev_value
        cond2_current = current_price if state.condition_2_metric == "price" else current_value
        cond2_fired = _crossed(state.condition_2_operator, cond2_prev, cond2_current, state.condition_2_threshold)

        if state.combinator == "AND":
            result = cond1_fired and cond2_fired
        elif state.combinator == "OR":
            result = cond1_fired or cond2_fired
        else:
            raise ValueError(f"combinator must be 'AND' or 'OR' when condition_2 is set, got {state.combinator!r}")

    state.prev_price = current_price
    state.prev_value = current_value

    return result
