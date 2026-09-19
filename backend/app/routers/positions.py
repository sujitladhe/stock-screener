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
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_session
from app.models import UserSession
from app import ventura_trading
from app.routers.orders import record_and_place_order

router = APIRouter(prefix="/positions", tags=["positions"])


class StoplossOrderRequest(BaseModel):
    trading_symbol: str
    # Deliberately NOT auto-derived from the position's side -- see
    # the NOTE in get_positions()'s docstring: the exact field Ventura
    # uses to indicate a position's long/short side hasn't been
    # confirmed yet, so guessing it here risks sending an exit order
    # in the WRONG direction with real money behind it. The frontend
    # shows the raw position data and asks the user to confirm B/S
    # explicitly until that's verified.
    transaction_type: str        # "B" or "S" -- must be the OPPOSITE of the position's side to actually exit it
    quantity: int
    order_type: str = "SLM"      # "SL" or "SLM"
    trigger_price: float = 0.0
    price: float = 0.0           # required for "SL", ignored by the broker for "SLM"
    order_kind: str = "intraday"
    product: str = "I"
    validity: str = "DAY"


@router.get("")
def get_positions(
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    """
    Live open + closed positions with broker-computed P&L. See
    ventura_trading.get_positions's docstring: field names beyond
    `profit_loss` aren't confirmed yet, so this passes the broker's
    response through largely as-is rather than remapping to a fixed
    shape the frontend might silently misread.
    """
    try:
        result = ventura_trading.get_positions(
            app_key=session.app_key,
            client_id=session.client_id,
            auth_token=session.ventura_auth_token,
        )
    except RuntimeError as e:
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
