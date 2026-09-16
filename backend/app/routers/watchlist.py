"""
routers/watchlist.py — per-user watchlist management.

Redesigned per explicit product decisions:
  - The "first leg / second leg" per-stock concept is REMOVED entirely.
  - Coloring now happens at the WATCHLIST level: each watchlist has one
    color, applied to every stock inside it.
  - A stock may belong to only ONE watchlist per user at a time. Adding
    it to a different watchlist automatically removes it from wherever
    it was before.

Endpoints:
  GET    /watchlists                  - list my watchlists, each with its stocks
  POST   /watchlists                  - create a new watchlist (name + color)
  DELETE /watchlists/{id}             - delete a watchlist (and its stocks)
  POST   /watchlists/{id}/stocks      - add a stock (auto-removes it from any other watchlist first)
  DELETE /watchlists/{id}/stocks/{stock_id} - remove a stock from a watchlist
  GET    /watchlists/stock-colors     - {trading_symbol: color} for ALL my watchlists combined,
                                         used by the screener to color rows
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_session
from app.models import UserSession, Watchlist, WatchlistStock, Instrument

router = APIRouter(prefix="/watchlists", tags=["watchlists"])


class CreateWatchlistRequest(BaseModel):
    name: str
    color: str = "#5b8cff"


class AddStockRequest(BaseModel):
    trading_symbol: str


def _serialize_watchlist(wl: Watchlist, stocks: list[WatchlistStock]) -> dict:
    return {
        "id": wl.id,
        "name": wl.name,
        "color": wl.color,
        "created_at": wl.created_at.isoformat(),
        "stocks": [
            {"id": s.id, "trading_symbol": s.trading_symbol, "added_at": s.added_at.isoformat()}
            for s in stocks
        ],
    }


def _get_owned_watchlist(db: Session, watchlist_id: int, client_id: str) -> Watchlist:
    wl = db.query(Watchlist).filter_by(id=watchlist_id, client_id=client_id).first()
    if not wl:
        raise HTTPException(status_code=404, detail="Watchlist not found.")
    return wl


@router.get("")
def list_watchlists(
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    watchlists = db.query(Watchlist).filter_by(client_id=session.client_id).order_by(Watchlist.created_at).all()
    result = []
    for wl in watchlists:
        stocks = db.query(WatchlistStock).filter_by(watchlist_id=wl.id).order_by(WatchlistStock.added_at).all()
        result.append(_serialize_watchlist(wl, stocks))
    return result


@router.post("")
def create_watchlist(
    req: CreateWatchlistRequest,
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Watchlist name cannot be empty.")

    existing = db.query(Watchlist).filter_by(client_id=session.client_id, name=name).first()
    if existing:
        raise HTTPException(status_code=409, detail="You already have a watchlist with this name.")

    wl = Watchlist(client_id=session.client_id, name=name, color=req.color)
    db.add(wl)
    db.commit()
    db.refresh(wl)
    return _serialize_watchlist(wl, [])


@router.delete("/{watchlist_id}")
def delete_watchlist(
    watchlist_id: int,
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    wl = _get_owned_watchlist(db, watchlist_id, session.client_id)
    db.query(WatchlistStock).filter_by(watchlist_id=wl.id).delete()
    db.delete(wl)
    db.commit()
    return {"status": "deleted"}


@router.post("/{watchlist_id}/stocks")
def add_stock(
    watchlist_id: int,
    req: AddStockRequest,
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    wl = _get_owned_watchlist(db, watchlist_id, session.client_id)

    instrument = (
        db.query(Instrument)
        .filter_by(trading_symbol=req.trading_symbol, exchange="NSE", instrument_type="EQ", is_active=True)
        .first()
    )
    if not instrument:
        raise HTTPException(status_code=404, detail=f"Unknown or inactive symbol: {req.trading_symbol}")

    # A stock may only be in ONE watchlist per user — if it's already
    # in a different one (or even this same one), remove that entry
    # first. This is the application-level enforcement; the DB's
    # unique constraint on (client_id, instrument_id) is the backstop.
    existing_anywhere = (
        db.query(WatchlistStock)
        .filter_by(client_id=session.client_id, instrument_id=instrument.id)
        .first()
    )
    moved_from = None
    if existing_anywhere:
        if existing_anywhere.watchlist_id == watchlist_id:
            return {"id": existing_anywhere.id, "trading_symbol": existing_anywhere.trading_symbol, "status": "already_in_watchlist"}
        moved_from = existing_anywhere.watchlist_id
        db.delete(existing_anywhere)
        db.flush()  # ensure the delete is applied before the insert, given the unique constraint

    stock = WatchlistStock(
        watchlist_id=wl.id,
        client_id=session.client_id,
        instrument_id=instrument.id,
        trading_symbol=instrument.trading_symbol,
    )
    db.add(stock)
    db.commit()
    db.refresh(stock)
    return {
        "id": stock.id,
        "trading_symbol": stock.trading_symbol,
        "status": "moved" if moved_from else "added",
        "moved_from_watchlist_id": moved_from,
    }


@router.delete("/{watchlist_id}/stocks/{stock_id}")
def remove_stock(
    watchlist_id: int,
    stock_id: int,
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    _get_owned_watchlist(db, watchlist_id, session.client_id)  # ownership check
    stock = db.query(WatchlistStock).filter_by(id=stock_id, watchlist_id=watchlist_id).first()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found in this watchlist.")

    db.delete(stock)
    db.commit()
    return {"status": "removed"}


@router.get("/stock-colors")
def get_stock_colors(
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    """
    Returns {trading_symbol: color} across ALL of the current user's
    watchlists — the screener uses this single lookup to tint rows.
    Since a stock can only be in one watchlist at a time now (unlike
    the old leg system), there's no ambiguity about which color wins.
    """
    rows = (
        db.query(WatchlistStock.trading_symbol, Watchlist.color)
        .join(Watchlist, WatchlistStock.watchlist_id == Watchlist.id)
        .filter(Watchlist.client_id == session.client_id)
        .all()
    )
    return {trading_symbol: color for trading_symbol, color in rows}
