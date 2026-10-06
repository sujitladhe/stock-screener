"""
routers/ignored.py — per-user, per-day stock ignore list for the Live screener.

A user can mark a stock as "ignored for today" so it is hidden even when it
keeps meeting the screener condition. The frontend filters the Live table using
this list. The backend broadcasts alerts for all stocks regardless of who has
ignored them; the ignore list is purely a display concern per user.

The list resets each day: only rows whose trade_date == today are considered
active. Old rows are left in the DB (cheap, and gives a history if ever needed)
but the GET endpoint returns only today's.

Endpoints:
  GET    /screener/ignored            – today's ignored symbols for current user
  POST   /screener/ignored            – ignore a stock for today
  DELETE /screener/ignored/{symbol}   – unignore one stock ("keep watch")
  DELETE /screener/ignored            – unignore all (watch all again)
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_session
from app.models import UserSession, IgnoredStock
from app.models import now_ist_naive

router = APIRouter(prefix="/screener/ignored", tags=["ignored"])


def _today() -> date:
    return now_ist_naive().date()


class IgnoreRequest(BaseModel):
    trading_symbol: str


@router.get("")
def list_ignored(
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    """Returns today's ignored trading symbols for the current user."""
    rows = (
        db.query(IgnoredStock)
        .filter_by(client_id=session.client_id, trade_date=_today())
        .order_by(IgnoredStock.ignored_at)
        .all()
    )
    return [
        {
            "trading_symbol": r.trading_symbol,
            "ignored_at": r.ignored_at.isoformat() if r.ignored_at else None,
        }
        for r in rows
    ]


@router.post("")
def ignore_stock(
    req: IgnoreRequest,
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    """Marks a stock as ignored for today. Idempotent — ignoring an already-ignored stock is fine."""
    symbol = req.trading_symbol.upper().strip()
    today = _today()

    existing = (
        db.query(IgnoredStock)
        .filter_by(client_id=session.client_id, trading_symbol=symbol, trade_date=today)
        .first()
    )
    if existing:
        return {"trading_symbol": symbol, "status": "already_ignored"}

    row = IgnoredStock(
        client_id=session.client_id,
        trading_symbol=symbol,
        trade_date=today,
    )
    db.add(row)
    db.commit()
    return {"trading_symbol": symbol, "status": "ignored"}


@router.delete("/{trading_symbol}")
def unignore_stock(
    trading_symbol: str,
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    """Removes one stock from today's ignore list ('keep watch')."""
    symbol = trading_symbol.upper().strip()
    row = (
        db.query(IgnoredStock)
        .filter_by(client_id=session.client_id, trading_symbol=symbol, trade_date=_today())
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"{symbol} is not in today's ignore list.")

    db.delete(row)
    db.commit()
    return {"trading_symbol": symbol, "status": "watching"}


@router.delete("")
def unignore_all(
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    """Removes ALL stocks from today's ignore list ('watch all again')."""
    db.query(IgnoredStock).filter_by(
        client_id=session.client_id, trade_date=_today()
    ).delete()
    db.commit()
    return {"status": "cleared"}
