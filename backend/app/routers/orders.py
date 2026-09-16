"""
routers/orders.py — order placement and management.

Every endpoint here uses get_current_session, giving us the CURRENT
LOGGED-IN USER's own app_key/client_id/auth_token -- orders are placed
on that specific person's Ventura account, never the shared service
account used elsewhere in this app for instruments/market data.

Starting deliberately small: this first version only has order
PLACEMENT, so we can test the single riskiest operation (a real order
hitting a real broker) in isolation before building order book
listing, cancellation, and positions on top of it.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_session
from app.models import UserSession, Order, Instrument
from app import ventura_trading

router = APIRouter(prefix="/orders", tags=["orders"])


class PlaceOrderRequest(BaseModel):
    trading_symbol: str
    order_kind: str          # "delivery" or "intraday"
    transaction_type: str    # "B" or "S"
    order_type: str          # "MKT", "LMT", "SL", "SLM"
    quantity: int
    product: str             # "C", "I", "M", "F" -- per Ventura's codes
    price: float = 0.0
    trigger_price: float = 0.0
    validity: str = "DAY"
    # Recorded for audit only -- not sent to Ventura, just stored
    # alongside the order so we know how the quantity was derived.
    stoploss_percentage: Optional[float] = None
    stoploss_value: Optional[float] = None


@router.post("/place")
def place_order(
    req: PlaceOrderRequest,
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    if req.order_kind not in ("delivery", "intraday"):
        raise HTTPException(status_code=400, detail="order_kind must be 'delivery' or 'intraday'")
    if req.transaction_type not in ("B", "S"):
        raise HTTPException(status_code=400, detail="transaction_type must be 'B' or 'S'")
    if req.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be positive")

    instrument = (
        db.query(Instrument)
        .filter_by(trading_symbol=req.trading_symbol, exchange="NSE", instrument_type="EQ", is_active=True)
        .first()
    )
    if not instrument:
        raise HTTPException(status_code=404, detail=f"Unknown or inactive symbol: {req.trading_symbol}")

    try:
        broker_response = ventura_trading.place_order(
            app_key=session.app_key,
            client_id=session.client_id,
            auth_token=session.ventura_auth_token,
            order_kind=req.order_kind,
            instrument_id=int(instrument.exchange_token),
            exchange="NSE",
            segment="E",
            transaction_type=req.transaction_type,
            order_type=req.order_type,
            quantity=req.quantity,
            product=req.product,
            price=req.price,
            trigger_price=req.trigger_price,
            validity=req.validity,
        )
    except RuntimeError as e:
        order_row = Order(
            client_id=session.client_id,
            instrument_id=instrument.id,
            trading_symbol=instrument.trading_symbol,
            order_kind=req.order_kind,
            transaction_type=req.transaction_type,
            order_type=req.order_type,
            product=req.product,
            quantity=req.quantity,
            price=req.price,
            trigger_price=req.trigger_price,
            validity=req.validity,
            stoploss_percentage=req.stoploss_percentage,
            stoploss_value=req.stoploss_value,
            status="Rejected",
            broker_message=str(e),
        )
        db.add(order_row)
        db.commit()
        raise HTTPException(status_code=502, detail=f"Could not reach broker: {e}")

    is_success = broker_response.get("status") == "success"

    order_row = Order(
        client_id=session.client_id,
        instrument_id=instrument.id,
        trading_symbol=instrument.trading_symbol,
        order_kind=req.order_kind,
        transaction_type=req.transaction_type,
        order_type=req.order_type,
        product=req.product,
        quantity=req.quantity,
        price=req.price,
        trigger_price=req.trigger_price,
        validity=req.validity,
        stoploss_percentage=req.stoploss_percentage,
        stoploss_value=req.stoploss_value,
        broker_order_no=broker_response.get("order_no"),
        status="Pending" if is_success else "Rejected",
        broker_message=broker_response.get("message"),
    )
    db.add(order_row)
    db.commit()
    db.refresh(order_row)

    if not is_success:
        raise HTTPException(status_code=400, detail=broker_response.get("message", "Order rejected by broker."))

    return {
        "id": order_row.id,
        "broker_order_no": order_row.broker_order_no,
        "status": order_row.status,
        "message": order_row.broker_message,
    }
