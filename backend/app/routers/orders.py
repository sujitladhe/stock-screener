"""
routers/orders.py — order placement and management.

Every endpoint here uses get_current_session, giving us the CURRENT
LOGGED-IN USER's own app_key/client_id/auth_token -- orders are placed
on that specific person's Ventura account, never the shared service
account used elsewhere in this app for instruments/market data.

Now covers: placement, listing (our own permanent record, synced
against the broker's live order book for today's still-open orders,
since Ventura's own Order Book only retains the current day per
ventura_trading.get_order_book's docstring), and cancellation.
Positions/live P&L are deliberately NOT in this file -- that's the
next piece to build on top of this.
"""

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_session
from app.models import UserSession, Order, Instrument
from app import ventura_trading

router = APIRouter(prefix="/orders", tags=["orders"])

# Statuses we already know are final -- no point spending a broker API
# call re-checking these on every /orders listing request.
TERMINAL_STATUSES = {"Executed", "Cancelled", "Rejected"}


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


def _serialize_order(o: Order) -> dict:
    return {
        "id": o.id,
        "trading_symbol": o.trading_symbol,
        "exchange": o.exchange,
        "order_kind": o.order_kind,
        "transaction_type": o.transaction_type,
        "order_type": o.order_type,
        "product": o.product,
        "quantity": o.quantity,
        "price": float(o.price) if o.price is not None else None,
        "trigger_price": float(o.trigger_price) if o.trigger_price is not None else None,
        "validity": o.validity,
        "stoploss_percentage": float(o.stoploss_percentage) if o.stoploss_percentage is not None else None,
        "stoploss_value": float(o.stoploss_value) if o.stoploss_value is not None else None,
        "broker_order_no": o.broker_order_no,
        "status": o.status,
        "broker_message": o.broker_message,
        "placed_at": o.placed_at.isoformat(),
        "last_status_check_at": o.last_status_check_at.isoformat() if o.last_status_check_at else None,
    }


def _sync_todays_open_orders_with_broker(db: Session, session: UserSession) -> None:
    """
    For any of THIS user's orders placed today that we don't already
    know are in a terminal state, ask the broker's own Order Book for
    its current status and update our row. Only today's orders are
    checked -- per ventura_trading.get_order_book's docstring, the
    broker itself only retains the current day, so there's nothing to
    reconcile for older orders (their status is frozen at whatever we
    last recorded, by design -- see the Order model's docstring).

    Best-effort: if the broker call itself fails (network blip, broker
    down), we leave existing rows untouched rather than raising --
    stale-but-present data beats a broken listing page.
    """
    today = date.today()
    open_orders = (
        db.query(Order)
        .filter(
            Order.client_id == session.client_id,
            Order.status.notin_(TERMINAL_STATUSES),
        )
        .all()
    )
    open_orders_today = [o for o in open_orders if o.placed_at.date() == today and o.broker_order_no]
    if not open_orders_today:
        return

    try:
        broker_orders = ventura_trading.get_order_book(
            app_key=session.app_key,
            client_id=session.client_id,
            auth_token=session.ventura_auth_token,
        )
    except RuntimeError:
        return  # best-effort -- see docstring above

    broker_status_by_order_no = {
        str(item.get("order_id")): item.get("status")
        for item in broker_orders
        if item.get("order_id") is not None
    }

    now = datetime.utcnow()
    for order in open_orders_today:
        broker_status = broker_status_by_order_no.get(str(order.broker_order_no))
        if broker_status and broker_status != order.status:
            order.status = broker_status
        order.last_status_check_at = now

    db.commit()


@router.get("")
def list_orders(
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    """
    Every order this user has ever placed through this app -- our own
    permanent record (requirement 6c), since Ventura's Order Book only
    keeps today's. Today's still-open orders are refreshed against the
    broker first, so "Open" here reflects real-time broker status, not
    just what we recorded at placement time.
    """
    _sync_todays_open_orders_with_broker(db, session)

    orders = (
        db.query(Order)
        .filter_by(client_id=session.client_id)
        .order_by(Order.placed_at.desc())
        .all()
    )
    return [_serialize_order(o) for o in orders]


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


@router.post("/{order_id}/cancel")
def cancel_order(
    order_id: int,
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    """
    Cancels an order via the broker (using THIS user's own session --
    same rule as placement, never the shared service account) and
    updates our persisted row to match.
    """
    order = db.query(Order).filter_by(id=order_id, client_id=session.client_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    if order.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=400, detail=f"Order is already {order.status.lower()} — cannot cancel.")

    if not order.broker_order_no:
        raise HTTPException(status_code=400, detail="Order has no broker order number — it may have been rejected at placement and was never live.")

    try:
        broker_response = ventura_trading.cancel_order(
            app_key=session.app_key,
            client_id=session.client_id,
            auth_token=session.ventura_auth_token,
            order_no=order.broker_order_no,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach broker: {e}")

    is_success = broker_response.get("status") == "success"

    order.broker_message = broker_response.get("message", order.broker_message)
    order.last_status_check_at = datetime.utcnow()
    if is_success:
        order.status = "Cancelled"
    db.commit()

    if not is_success:
        raise HTTPException(status_code=400, detail=broker_response.get("message", "Broker declined to cancel this order."))

    return {
        "id": order.id,
        "status": order.status,
        "message": order.broker_message,
    }
