"""
routers/positions.py — live positions + P&L (requirement 7), and
placing a stoploss/exit order against a running position (requirement
8a).

Positions themselves are NOT stored in our DB -- they're derived
broker-side state (what you currently hold), so there's nothing to
persist; we just proxy the broker's live answer on every request. This
mirrors ventura_trading.get_positions's own reasoning: the broker's
P&L figure is authoritative, so we don't try to recompute or cache it.

Placing a stoploss order for a position is just a normal order (an SL
or SLM order in the OPPOSITE direction of the position, sized to some
or all of the held quantity) -- it goes through orders.py's
record_and_place_order() so it gets identical handling (DB audit row,
rejection bookkeeping, broker-credential rule) to any other order
placed from this app, rather than a separate parallel path.

Token-expiry retry: if Ventura returns HTTP 401 on get_positions, we
force-refresh the token and retry once. Ventura can invalidate tokens
server-side before our stored auth_expiry, so we cannot rely on the
local check alone.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_session
from app.models import UserSession
from app import ventura_trading
from app.session_service import refresh_session_token
from app.routers.orders import record_and_place_order

router = APIRouter(prefix="/positions", tags=["positions"])


class StoplossOrderRequest(BaseModel):
    trading_symbol: str
    transaction_type: str        # "B" or "S"
    quantity: int
    order_type: str = "SLM"      # "SL" or "SLM"
    trigger_price: float = 0.0
    price: float = 0.0
    order_kind: str = "intraday"
    product: str = "I"
    validity: str = "DAY"


@router.get("")
def get_positions(
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    """
    Live open + closed positions with broker-computed P&L.
    Retries once with a refreshed token if Ventura returns 401.
    """
    def _fetch():
        return ventura_trading.get_positions(
            app_key=session.app_key,
            client_id=session.client_id,
            auth_token=session.ventura_auth_token,
        )

    try:
        result = _fetch()
    except RuntimeError as e:
        if "HTTP 401" in str(e):
            # Ventura invalidated the token server-side. Refresh and retry once.
            try:
                refresh_session_token(db, session)
                result = _fetch()
            except Exception as e2:
                raise HTTPException(status_code=502, detail=f"Could not reach broker: {e2}")
        else:
            raise HTTPException(status_code=502, detail=f"Could not reach broker: {e}")

    return {
        "open_positions": result.get("open_positions", []),
        "closed_positions": result.get("closed_positions", []),
    }


@router.post("/stoploss")
def place_stoploss_for_position(
    req: StoplossOrderRequest,
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    if req.order_type not in ("SL", "SLM"):
        raise HTTPException(status_code=400, detail="order_type must be 'SL' or 'SLM' for a stoploss order")
    if req.trigger_price <= 0:
        raise HTTPException(status_code=400, detail="trigger_price must be positive for a stoploss order")

    return record_and_place_order(
        db, session,
        trading_symbol=req.trading_symbol,
        order_kind=req.order_kind,
        transaction_type=req.transaction_type,
        order_type=req.order_type,
        quantity=req.quantity,
        product=req.product,
        price=req.price,
        trigger_price=req.trigger_price,
        validity=req.validity,
    )
