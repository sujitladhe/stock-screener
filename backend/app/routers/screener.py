"""
routers/screener.py — the endpoints the web UI talks to.

GET  /screener/today            — today's screener hits so far.
GET  /screener/history          — a past day's screener hits, by date.
GET  /screener/available-dates  — which dates actually have data, so
                                   the frontend's date picker doesn't
                                   guess at valid days.
WS   /ws/screener                — live push for today's hits only.

NOTE on what columns are NOT here yet: your requirements doc also asks
for "current %", "remaining % to circuit", "circuit price", and "FNO
or Non-FNO" per stock. We deliberately deferred sourcing that data
much earlier in this build (Ventura/Angel don't obviously provide
circuit limits or an F&O flag in what we've pulled so far) — so those
columns are simply absent from this response for now, not silently
wrong.
"""

from datetime import date

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models import ScreenerDailyStat, UserSession
from app.ws_manager import manager
from app.config import settings

router = APIRouter(tags=["screener"])


def _identify_client_id_from_cookie(websocket: WebSocket) -> str | None:
    """
    Best-effort identification of the connecting user, for targeted
    alert delivery (see ws_manager.send_to_client). Deliberately does
    NOT do the auto-relogin dance get_current_session does for HTTP
    requests — if we can't cleanly identify the user, the connection
    still proceeds and gets the shared screener feed, just without
    personal alert delivery, rather than rejecting the connection
    outright over what might just be an expired/stale cookie.
    """
    session_token = websocket.cookies.get(settings.session_cookie_name)
    if not session_token:
        print(f"[screener ws] No session cookie found on WebSocket connect — "
              f"personal alerts won't be delivered to this connection.")
        return None

    db = SessionLocal()
    try:
        session_row = db.query(UserSession).filter_by(session_token=session_token, is_active=True).first()
        client_id = session_row.client_id if session_row else None
        if client_id:
            print(f"[screener ws] Identified connecting user as client_id={client_id}")
        else:
            print(f"[screener ws] Session cookie present but no matching active UserSession found — "
                  f"personal alerts won't be delivered to this connection.")
        return client_id
    finally:
        db.close()


def _serialize(row: ScreenerDailyStat) -> dict:
    return {
        "trading_symbol": row.trading_symbol,
        "occurrence_count": row.occurrence_count,
        "first_triggered_at": row.first_triggered_at.isoformat(),
        "last_triggered_at": row.last_triggered_at.isoformat(),
        "ltp": float(row.last_ltp),
        "multiple": float(row.last_multiple),
        "value": float(row.last_value),
        "current_minute_volume": row.last_current_minute_volume,
        "avg_volume_per_min": float(row.last_avg_volume_per_min),
        "prev_close": float(row.last_prev_close) if row.last_prev_close is not None else None,
        "condition_matched": row.last_condition_matched,
    }


def _query_for_date(db: Session, trade_date: date, search: str = None):
    query = db.query(ScreenerDailyStat).filter(ScreenerDailyStat.trade_date == trade_date)
    if search:
        query = query.filter(ScreenerDailyStat.trading_symbol.ilike(f"%{search}%"))
    return query.order_by(ScreenerDailyStat.last_triggered_at.desc()).all()


@router.get("/screener/today")
def get_today_screener(
    search: str = Query(default=None, description="Filter by trading symbol, case-insensitive substring match"),
    db: Session = Depends(get_db),
):
    rows = _query_for_date(db, date.today(), search)
    return [_serialize(row) for row in rows]


@router.get("/screener/history")
def get_history_screener(
    date_str: str = Query(alias="date", description="YYYY-MM-DD"),
    search: str = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        trade_date = date.fromisoformat(date_str)
    except ValueError:
        return {"error": "Invalid date format, expected YYYY-MM-DD"}

    if trade_date > date.today():
        return {"error": "Cannot request a future date"}

    rows = _query_for_date(db, trade_date, search)
    return [_serialize(row) for row in rows]


@router.get("/screener/available-dates")
def get_available_dates(db: Session = Depends(get_db)):
    """
    Returns every distinct date that has at least one screener hit,
    most recent first — so the frontend's date picker only ever shows
    days that actually have data, instead of guessing.
    """
    results = (
        db.query(ScreenerDailyStat.trade_date)
        .distinct()
        .order_by(ScreenerDailyStat.trade_date.desc())
        .all()
    )
    return [r[0].isoformat() for r in results]


@router.websocket("/ws/screener")
async def websocket_screener(websocket: WebSocket):
    client_id = _identify_client_id_from_cookie(websocket)
    await manager.connect(websocket, client_id=client_id)
    try:
        while True:
            # We don't expect the browser to send anything meaningful —
            # this just keeps the connection open and lets us detect
            # a disconnect (the receive raises WebSocketDisconnect).
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
