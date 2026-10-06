"""
auto_trade_registry.py — LIVE in-memory set of ACTIVE auto orders the
running tick engine checks on every tick, keyed by trading_symbol.

Updated in 0004: _state_from_order now maps auto_day_high_pct_limit.
"""

import threading

from app.auto_trade_engine import AutoOrderState

_lock = threading.Lock()

_registry: dict = {}


def _state_from_order(order) -> AutoOrderState:
    """order: an app.models.Order row with source='auto'."""
    return AutoOrderState(
        order_id=order.id,
        client_id=order.client_id,
        trading_symbol=order.trading_symbol,
        volume_threshold=float(order.auto_volume_threshold) if order.auto_volume_threshold is not None else None,
        candle_pct_threshold=float(order.auto_candle_pct_threshold) if order.auto_candle_pct_threshold is not None else None,
        combinator=order.auto_combinator,
        valid_till=order.auto_valid_till,
        day_high_pct_limit=float(order.auto_day_high_pct_limit) if order.auto_day_high_pct_limit is not None else None,
    )


def _remove_locked(order_id: int) -> None:
    for symbol, states in list(_registry.items()):
        kept = [s for s in states if s.order_id != order_id]
        if kept:
            _registry[symbol] = kept
        else:
            del _registry[symbol]


def add_order(order) -> None:
    """Idempotent: adding an order that's already present replaces it."""
    state = _state_from_order(order)
    with _lock:
        _remove_locked(order.id)
        _registry.setdefault(state.trading_symbol, []).append(state)


def remove_order(order_id: int) -> None:
    with _lock:
        _remove_locked(order_id)


def get_orders_for_symbol(trading_symbol: str) -> list:
    with _lock:
        return list(_registry.get(trading_symbol, ()))


def has_orders() -> bool:
    return bool(_registry)


def count() -> int:
    with _lock:
        return sum(len(v) for v in _registry.values())


def load_all(db_session_factory) -> None:
    from app.models import Order

    db = db_session_factory()
    try:
        active = db.query(Order).filter(Order.source == "auto", Order.status == "Active").all()
        for order in active:
            add_order(order)
        print(f"[auto_trade_registry] Loaded {len(active)} active auto order(s) across {len(_registry)} symbol(s).")
    finally:
        db.close()
