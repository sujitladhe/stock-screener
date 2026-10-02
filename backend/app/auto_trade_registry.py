"""
auto_trade_registry.py — the LIVE, in-memory set of ACTIVE auto orders
the running tick engine checks on every tick, keyed by trading_symbol.

Same idea as alert_registry.py (a plain module-level dict shared by the
orders router and ws_client.py's tick loop), with one difference: this
one is guarded by a threading.Lock. FastAPI runs plain `def` route
handlers in a worker thread pool, so create/cancel requests can touch
this dict at the same moment the event-loop thread is iterating it on a
tick. Auto orders move real money, so a lock is cheap insurance.

Life cycle of an entry:
  - added when an auto order is created (orders router) or re-loaded
    from the DB when the engine starts (load_all);
  - removed when the user cancels it, or the instant the engine decides
    to fire it (before the broker call even starts — this is what stops
    a second tick from firing the same order twice). The database row is
    the source of truth for the outcome; see auto_trade_service.
"""

import threading

from app.auto_trade_engine import AutoOrderState

_lock = threading.Lock()

# trading_symbol -> list of AutoOrderState for ACTIVE auto orders on that stock
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
    """A COPY of the list, so callers can iterate while others mutate."""
    with _lock:
        return list(_registry.get(trading_symbol, ()))


def has_orders() -> bool:
    """Cheap, lock-free 'is there anything to check at all' test for the hot path."""
    return bool(_registry)


def count() -> int:
    with _lock:
        return sum(len(v) for v in _registry.values())


def load_all(db_session_factory) -> None:
    """
    Rebuilds the registry from the DB — called when the engine starts.
    db_session_factory: a callable returning a new DB session (e.g.
    app.database.SessionLocal), passed in to avoid a circular import.
    """
    from app.models import Order

    db = db_session_factory()
    try:
        active = db.query(Order).filter(Order.source == "auto", Order.status == "Active").all()
        # Deliberately NOT clearing first: an order created through the
        # API a moment before this query would be wiped. add_order() is
        # idempotent, and a stale entry is harmless anyway — the DB
        # claim in auto_trade_service only lets a still-Active order fire.
        for order in active:
            add_order(order)
        print(f"[auto_trade_registry] Loaded {len(active)} active auto order(s) across {len(_registry)} symbol(s).")
    finally:
        db.close()
