"""
routers/instruments.py — read-only lookups against our shared
instrument master (~2,655 NSE stocks). Currently just search-as-you-
type, used by the Watchlist page to add a stock directly without it
needing to already be in the screener.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_session
from app.models import Instrument, UserSession

router = APIRouter(prefix="/instruments", tags=["instruments"])


@router.get("/search")
def search_instruments(
    q: str = Query(..., min_length=1, description="Partial trading symbol or name"),
    limit: int = Query(default=15, le=50),
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    """
    Matches trading_symbol PREFIX first (what you'd expect typing a
    ticker -- "RELI" should surface RELIANCE before anything with
    "reli" buried mid-name), then falls back to a substring match
    against symbol or company name, combined and de-duplicated.
    """
    prefix_matches = (
        db.query(Instrument)
        .filter(
            Instrument.exchange == "NSE",
            Instrument.instrument_type == "EQ",
            Instrument.is_active == True,  # noqa: E712
            Instrument.trading_symbol.ilike(f"{q}%"),
        )
        .order_by(Instrument.trading_symbol)
        .limit(limit)
        .all()
    )

    results = list(prefix_matches)
    if len(results) < limit:
        seen_symbols = {r.trading_symbol for r in results}
        substring_matches = (
            db.query(Instrument)
            .filter(
                Instrument.exchange == "NSE",
                Instrument.instrument_type == "EQ",
                Instrument.is_active == True,  # noqa: E712
                (Instrument.trading_symbol.ilike(f"%{q}%") | Instrument.name.ilike(f"%{q}%")),
            )
            .order_by(Instrument.trading_symbol)
            .limit(limit * 2)  # overfetch a bit since we'll filter out ones we already have
            .all()
        )
        for inst in substring_matches:
            if inst.trading_symbol not in seen_symbols:
                results.append(inst)
                seen_symbols.add(inst.trading_symbol)
                if len(results) >= limit:
                    break

    return [{"trading_symbol": r.trading_symbol, "name": r.name} for r in results]
