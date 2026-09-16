"""
alert_registry.py — the LIVE, in-memory set of active alerts the
running tick engine checks against, keyed by trading_symbol.

This is deliberately a plain module-level dict, not a class instance
passed around -- both routers/alerts.py (when a user creates/toggles/
deletes an alert) and ws_client.py (on every tick) import this same
module and see the same state, since Python caches module imports.
Safe to mutate directly: everything in this app runs on a single
asyncio event loop, so there's no multi-threaded race condition here,
only interleaved async tasks -- and plain dict/list mutations between
await points are atomic enough for this use case.

Loaded fresh from the DB once at engine startup (see load_all() in
ws_client.py), then kept in sync incrementally by the alerts API for
anything created/changed/removed while the engine is already running.
"""

from app.alert_engine import AlertRuntimeState

# trading_symbol -> list of AlertRuntimeState for alerts on that stock
_registry = {}


def add_alert(alert) -> None:
    """
    alert: an app.models.Alert row (freshly created or just
    reactivated). Builds a fresh AlertRuntimeState -- meaning crossing
    detection starts clean (no prev_price/prev_value yet), which is
    correct: we don't know what happened before this alert existed.
    """
    state = AlertRuntimeState(
        alert_id=alert.id,
        client_id=alert.client_id,
        trading_symbol=alert.trading_symbol,
        condition_1_metric=alert.condition_1_metric,
        condition_1_operator=alert.condition_1_operator,
        condition_1_threshold=float(alert.condition_1_threshold),
        condition_2_metric=alert.condition_2_metric,
        condition_2_operator=alert.condition_2_operator,
        condition_2_threshold=float(alert.condition_2_threshold) if alert.condition_2_threshold is not None else None,
        combinator=alert.combinator,
    )
    remove_alert(alert.id)
    _registry.setdefault(alert.trading_symbol, []).append(state)


def remove_alert(alert_id: int) -> None:
    for symbol, states in list(_registry.items()):
        _registry[symbol] = [s for s in states if s.alert_id != alert_id]
        if not _registry[symbol]:
            del _registry[symbol]


def get_alerts_for_symbol(trading_symbol: str) -> list:
    return _registry.get(trading_symbol, [])


def load_all(db_session_factory) -> None:
    """
    Populates the registry from the DB -- called once when the engine
    starts. db_session_factory: a callable returning a new DB session
    (e.g. app.database.SessionLocal), to avoid a circular import with
    app.models at module load time.
    """
    from app.models import Alert

    _registry.clear()
    db = db_session_factory()
    try:
        active_alerts = db.query(Alert).filter_by(is_active=True).all()
        for alert in active_alerts:
            add_alert(alert)
        print(f"[alert_registry] Loaded {len(active_alerts)} active alert(s) across {len(_registry)} symbol(s).")
    finally:
        db.close()
