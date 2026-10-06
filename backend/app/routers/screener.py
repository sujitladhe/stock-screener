"""
routers/screener.py — the endpoints the web UI talks to.

GET  /screener/today            — today's screener hits so far.
GET  /screener/history          — a past day's screener hits, by date.
GET  /screener/available-dates  — which dates actually have data.
WS   /ws/screener               — live push for today's hits only.

Updated in 0004: _serialize now includes circuit_pct and candle_pct.
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
    session_token = websocket.cookies.get(settings.session_cookie_name)
    if not session_token:
        print(f"[screener ws] No session cookie found — personal alerts won't be delivered.")
        return None

    db = SessionLocal()
    try:
        session_row = db.query(UserSession).filter_by(session_token=session_token, is_active=True).first()
        client_id = session_row.client_id if session_row else None
        if client_id:
            print(f"[screener ws] Identified connecting user as client_id={client_id}")
        else:
            print(f"[screener ws] No matching active session — personal alerts won't be delivered.")
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
        # New in 0004 — may be None for rows written before the migration
        "circuit_pct": row.last_circuit_pct,
        "candle_pct": float(row.last_candle_pct) if row.last_candle_pct is not None else None,
    }


def _query_for_date(db: Session, trade_date: date, search: str = None):
    query = db.query(ScreenerDailyStat).filter(ScreenerDailyStat.trade_date == trade_date)
    if search:
        query = query.filter(ScreenerDailyStat.trading_symbol.ilike(f"%{search}%"))
    return query.order_by(ScreenerDailyStat.last_triggered_at.desc()).all()


@router.get("/screener/today")
def get_today_screener(
    search: str = Query(default=None),
    db: Session = Depends(get_db),
):
    rows = _query_for_date(db, date.today(), search)
    return [_serialize(row) for row in rows]


@router.get("/screener/history")
def get_history_screener(
    date_str: str = Query(alias="date"),
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
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
