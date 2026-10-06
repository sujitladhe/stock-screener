"""
routers/orders.py — order placement and management.

Changes in 0004:
  - CreateAutoOrderRequest: new fields auto_expires_daily, day_high_pct_limit.
  - _serialize_order: includes the two new fields.
  - _validate_auto_order: validates day_high_pct_limit range.
  - create_auto_order / update_auto_order: persist the new fields.
"""

from datetime import time as dtime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_session
from app.models import UserSession, Order, Instrument, VolumeAverage, now_ist_naive
from app import ventura_trading
from app import auto_trade_registry
from app.auto_trade_engine import MARKET_OPEN, MARKET_CLOSE

router = APIRouter(prefix="/orders", tags=["orders"])

TERMINAL_STATUSES = {"Executed", "Cancelled", "Rejected"}
VALID_SOURCES = {"manual", "auto", "all"}
VALID_ORDER_TYPES = {"MKT", "LMT", "SL", "SLM"}
VALID_VALIDITIES = {"DAY", "IOC"}
PRODUCTS_BY_KIND = {"delivery": {"C"}, "intraday": {"I", "M"}}


class PlaceOrderRequest(BaseModel):
    trading_symbol: str
    order_kind: str
    transaction_type: str
    order_type: str
    quantity: int
    product: str
    price: float = 0.0
    trigger_price: float = 0.0
    validity: str = "DAY"
    stoploss_percentage: Optional[float] = None
    stoploss_value: Optional[float] = None


class CreateAutoOrderRequest(PlaceOrderRequest):
    volume_threshold: Optional[float] = None
    candle_pct_threshold: Optional[float] = None
    combinator: Optional[str] = None
    valid_till: Optional[str] = None
    # NEW (0004)
    day_high_pct_limit: Optional[float] = None   # skip if stock is already up >= this % for the day
    auto_expires_daily: bool = False              # True = "today only"; False = "until executed"


class ModifyOrderRequest(BaseModel):
    quantity: Optional[int] = None
    order_type: Optional[str] = None
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    validity: Optional[str] = None


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
        # auto trade
        "source": o.source or "manual",
        "auto_volume_threshold": float(o.auto_volume_threshold) if o.auto_volume_threshold is not None else None,
        "auto_candle_pct_threshold": float(o.auto_candle_pct_threshold) if o.auto_candle_pct_threshold is not None else None,
        "auto_combinator": o.auto_combinator,
        "auto_valid_till": o.auto_valid_till.strftime("%H:%M") if o.auto_valid_till else None,
        "triggered_at": o.triggered_at.isoformat() if o.triggered_at else None,
        "trigger_details": o.trigger_details,
        # NEW (0004)
        "auto_expires_daily": bool(o.auto_expires_daily) if o.auto_expires_daily is not None else False,
        "auto_day_high_pct_limit": float(o.auto_day_high_pct_limit) if o.auto_day_high_pct_limit is not None else None,
    }


def _parse_valid_till(value: Optional[str]) -> Optional[dtime]:
    if value is None or not value.strip():
        return None
    text = value.strip()
    try:
        parts = [int(p) for p in text.split(":")]
        if len(parts) not in (2, 3):
            raise ValueError
        parsed = dtime(parts[0], parts[1])
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="valid_till must be a time like 09:30 (24-hour, IST).")

    if parsed < MARKET_OPEN or parsed > MARKET_CLOSE:
        raise HTTPException(
            status_code=400,
            detail="valid_till must be between 09:15 and 15:30 (IST).",
        )
    return parsed


def _validate_auto_order(req: CreateAutoOrderRequest) -> Optional[dtime]:
    if req.order_kind not in ("delivery", "intraday"):
        raise HTTPException(status_code=400, detail="order_kind must be 'delivery' or 'intraday'")
    if req.transaction_type not in ("B", "S"):
        raise HTTPException(status_code=400, detail="transaction_type must be 'B' or 'S'")
    if req.order_type not in VALID_ORDER_TYPES:
        raise HTTPException(status_code=400, detail=f"order_type must be one of {sorted(VALID_ORDER_TYPES)}")
    if req.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be positive")
    if req.validity not in VALID_VALIDITIES:
        raise HTTPException(status_code=400, detail=f"validity must be one of {sorted(VALID_VALIDITIES)}")
    if req.product not in PRODUCTS_BY_KIND[req.order_kind]:
        raise HTTPException(
            status_code=400,
            detail=f"product '{req.product}' isn't valid for a {req.order_kind} order.",
        )
    if req.order_type in ("LMT", "SL") and req.price <= 0:
        raise HTTPException(status_code=400, detail=f"A {req.order_type} order needs a price.")
    if req.order_type in ("SL", "SLM") and req.trigger_price <= 0:
        raise HTTPException(status_code=400, detail=f"A {req.order_type} order needs a trigger price.")

    if req.volume_threshold is None and req.candle_pct_threshold is None:
        raise HTTPException(
            status_code=400,
            detail="Set at least one condition: a volume value, a candle %, or both.",
        )
    if req.volume_threshold is not None and req.volume_threshold <= 0:
        raise HTTPException(status_code=400, detail="volume_threshold must be greater than 0.")
    if req.candle_pct_threshold is not None and req.candle_pct_threshold <= 0:
        raise HTTPException(status_code=400, detail="candle_pct_threshold must be greater than 0.")
    if req.volume_threshold is not None and req.candle_pct_threshold is not None:
        if req.combinator not in ("AND", "OR"):
            raise HTTPException(status_code=400, detail="combinator must be 'AND' or 'OR'.")

    # NEW (0004)
    if req.day_high_pct_limit is not None:
        if req.day_high_pct_limit <= 0 or req.day_high_pct_limit >= 100:
            raise HTTPException(
                status_code=400,
                detail="day_high_pct_limit must be between 0 and 100 (exclusive).",
            )

    return _parse_valid_till(req.valid_till)


def _lookup_tradeable_instrument(db: Session, trading_symbol: str) -> Instrument:
    instrument = (
        db.query(Instrument)
        .filter_by(trading_symbol=trading_symbol, exchange="NSE", instrument_type="EQ", is_active=True)
        .first()
    )
    if not instrument:
        raise HTTPException(status_code=404, detail=f"Unknown or inactive symbol: {trading_symbol}")

    has_live_feed = db.query(VolumeAverage).filter_by(instrument_id=instrument.id).first()
    if not has_live_feed:
        raise HTTPException(
            status_code=400,
            detail=f"{instrument.trading_symbol} isn't in the live feed yet (no volume average computed).",
        )
    return instrument


def _sync_todays_open_orders_with_broker(db: Session, session: UserSession) -> None:
    today = now_ist_naive().date()
    open_orders = (
        db.query(Order)
        .filter(Order.client_id == session.client_id, Order.status.notin_(TERMINAL_STATUSES))
        .all()
    )
    open_orders_today = [
        o for o in open_orders
        if o.broker_order_no and (o.triggered_at or o.placed_at).date() == today
    ]
    if not open_orders_today:
        return

    try:
        broker_orders = ventura_trading.get_order_book(
            app_key=session.app_key,
            client_id=session.client_id,
            auth_token=session.ventura_auth_token,
        )
    except RuntimeError:
        return

    broker_status_by_order_no = {
        str(item.get("order_id")): item.get("status")
        for item in broker_orders
        if item.get("order_id") is not None
    }

    now = now_ist_naive()
    for order in open_orders_today:
        broker_status = broker_status_by_order_no.get(str(order.broker_order_no))
        if broker_status and broker_status != order.status:
            order.status = broker_status
        order.last_status_check_at = now

    db.commit()


def record_and_place_order(
    db: Session,
    session: UserSession,
    *,
    trading_symbol: str,
    order_kind: str,
    transaction_type: str,
    order_type: str,
    quantity: int,
    product: str,
    price: float = 0.0,
    trigger_price: float = 0.0,
    validity: str = "DAY",
    stoploss_percentage: Optional[float] = None,
    stoploss_value: Optional[float] = None,
) -> dict:
    if order_kind not in ("delivery", "intraday"):
        raise HTTPException(status_code=400, detail="order_kind must be 'delivery' or 'intraday'")
    if transaction_type not in ("B", "S"):
        raise HTTPException(status_code=400, detail="transaction_type must be 'B' or 'S'")
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be positive")

    instrument = (
        db.query(Instrument)
        .filter_by(trading_symbol=trading_symbol, exchange="NSE", instrument_type="EQ", is_active=True)
        .first()
    )
    if not instrument:
        raise HTTPException(status_code=404, detail=f"Unknown or inactive symbol: {trading_symbol}")

    try:
        broker_response = ventura_trading.place_order(
            app_key=session.app_key,
            client_id=session.client_id,
            auth_token=session.ventura_auth_token,
            order_kind=order_kind,
            instrument_id=int(instrument.exchange_token),
            exchange="NSE",
            segment="E",
            transaction_type=transaction_type,
            order_type=order_type,
            quantity=quantity,
            product=product,
            price=price,
            trigger_price=trigger_price,
            validity=validity,
        )
    except RuntimeError as e:
        order_row = Order(
            client_id=session.client_id,
            instrument_id=instrument.id,
            trading_symbol=instrument.trading_symbol,
            order_kind=order_kind,
            transaction_type=transaction_type,
            order_type=order_type,
            product=product,
            quantity=quantity,
            price=price,
            trigger_price=trigger_price,
            validity=validity,
            stoploss_percentage=stoploss_percentage,
            stoploss_value=stoploss_value,
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
        order_kind=order_kind,
        transaction_type=transaction_type,
        order_type=order_type,
        product=product,
        quantity=quantity,
        price=price,
        trigger_price=trigger_price,
        validity=validity,
        stoploss_percentage=stoploss_percentage,
        stoploss_value=stoploss_value,
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


@router.get("")
def list_orders(
    source: str = Query(default="all"),
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    if source not in VALID_SOURCES:
        raise HTTPException(status_code=400, detail=f"source must be one of {sorted(VALID_SOURCES)}")

    _sync_todays_open_orders_with_broker(db, session)

    query = db.query(Order).filter_by(client_id=session.client_id)
    if source != "all":
        query = query.filter(Order.source == source)

    orders = query.order_by(Order.placed_at.desc()).all()
    return [_serialize_order(o) for o in orders]


@router.post("/place")
def place_order(
    req: PlaceOrderRequest,
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
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
        stoploss_percentage=req.stoploss_percentage,
        stoploss_value=req.stoploss_value,
    )


@router.post("/auto")
def create_auto_order(
    req: CreateAutoOrderRequest,
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    valid_till = _validate_auto_order(req)
    instrument = _lookup_tradeable_instrument(db, req.trading_symbol)

    # Server-side duplicate guard — the frontend warning is UX-only and can be bypassed
    # (e.g. by opening the drawer before autoOrderSymbols has loaded). The backend is the
    # real enforcement layer. Only one Active auto order per (client, symbol) is allowed.
    existing_active = (
        db.query(Order)
        .filter_by(
            client_id=session.client_id,
            trading_symbol=instrument.trading_symbol,
            source="auto",
            status="Active",
        )
        .first()
    )
    if existing_active:
        raise HTTPException(
            status_code=409,
            detail=(
                f"You already have an active auto order for {instrument.trading_symbol} "
                f"(order #{existing_active.id}). Cancel it before creating a new one."
            ),
        )

    order = Order(
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
        status="Active",
        broker_message="Waiting for the trigger condition. Not sent to the broker yet.",
        source="auto",
        auto_volume_threshold=req.volume_threshold,
        auto_candle_pct_threshold=req.candle_pct_threshold,
        auto_combinator=req.combinator if (req.volume_threshold is not None and req.candle_pct_threshold is not None) else None,
        auto_valid_till=valid_till,
        # NEW (0004)
        auto_expires_daily=req.auto_expires_daily,
        auto_day_high_pct_limit=req.day_high_pct_limit,
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    auto_trade_registry.add_order(order)

    return _serialize_order(order)


@router.patch("/{order_id}/auto")
def update_auto_order(
    order_id: int,
    req: CreateAutoOrderRequest,
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    order = (
        db.query(Order)
        .filter_by(id=order_id, client_id=session.client_id, source="auto")
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Auto order not found.")
    if order.status != "Active":
        raise HTTPException(
            status_code=400,
            detail=f"Only a still-waiting (Active) auto order can be edited (this one is {order.status}).",
        )

    valid_till = _validate_auto_order(req)
    instrument = _lookup_tradeable_instrument(db, req.trading_symbol)

    update_fields = {
        "instrument_id": instrument.id,
        "trading_symbol": instrument.trading_symbol,
        "order_kind": req.order_kind,
        "transaction_type": req.transaction_type,
        "order_type": req.order_type,
        "product": req.product,
        "quantity": req.quantity,
        "price": req.price,
        "trigger_price": req.trigger_price,
        "validity": req.validity,
        "stoploss_percentage": req.stoploss_percentage,
        "stoploss_value": req.stoploss_value,
        "auto_volume_threshold": req.volume_threshold,
        "auto_candle_pct_threshold": req.candle_pct_threshold,
        "auto_combinator": req.combinator if (req.volume_threshold is not None and req.candle_pct_threshold is not None) else None,
        "auto_valid_till": valid_till,
        "broker_message": "Waiting for the trigger condition. Not sent to the broker yet.",
        # NEW (0004)
        "auto_expires_daily": req.auto_expires_daily,
        "auto_day_high_pct_limit": req.day_high_pct_limit,
    }

    changed = (
        db.query(Order)
        .filter(Order.id == order.id, Order.status == "Active")
        .update(update_fields, synchronize_session=False)
    )
    db.commit()
    if not changed:
        raise HTTPException(
            status_code=409,
            detail="This auto order triggered at the same moment and could not be edited.",
        )

    db.refresh(order)
    auto_trade_registry.add_order(order)

    return _serialize_order(order)


@router.post("/{order_id}/cancel")
def cancel_order(
    order_id: int,
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    order = db.query(Order).filter_by(id=order_id, client_id=session.client_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    if order.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=400, detail=f"Order is already {order.status.lower()}.")

    if order.source == "auto" and order.status == "Triggering":
        raise HTTPException(
            status_code=409,
            detail="This auto order is being placed right now. Refresh in a moment.",
        )

    if order.source == "auto" and order.status == "Active":
        changed = (
            db.query(Order)
            .filter(Order.id == order.id, Order.status == "Active")
            .update(
                {
                    "status": "Cancelled",
                    "broker_message": "Auto order cancelled before it triggered.",
                    "last_status_check_at": now_ist_naive(),
                },
                synchronize_session=False,
            )
        )
        db.commit()
        auto_trade_registry.remove_order(order.id)
        if not changed:
            raise HTTPException(
                status_code=409,
                detail="This auto order triggered at the same moment and could not be cancelled.",
            )
        db.refresh(order)
        return {"id": order.id, "status": order.status, "message": order.broker_message}

    if not order.broker_order_no:
        raise HTTPException(status_code=400, detail="Order has no broker order number.")

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
    order.last_status_check_at = now_ist_naive()
    if is_success:
        order.status = "Cancelled"
    db.commit()

    if not is_success:
        raise HTTPException(status_code=400, detail=broker_response.get("message", "Broker declined to cancel."))

    return {"id": order.id, "status": order.status, "message": order.broker_message}


@router.patch("/{order_id}/modify")
def modify_order(
    order_id: int,
    req: ModifyOrderRequest,
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    order = db.query(Order).filter_by(id=order_id, client_id=session.client_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    if order.status != "Pending":
        raise HTTPException(status_code=400, detail=f"Only a Pending order can be modified (this one is {order.status}).")
    if not order.broker_order_no:
        raise HTTPException(status_code=400, detail="Order has no broker order number.")

    new_quantity = req.quantity if req.quantity is not None else order.quantity
    new_order_type = req.order_type if req.order_type is not None else order.order_type
    new_price = req.price if req.price is not None else float(order.price or 0)
    new_trigger_price = req.trigger_price if req.trigger_price is not None else float(order.trigger_price or 0)
    new_validity = req.validity if req.validity is not None else order.validity

    if new_quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be positive")

    try:
        broker_response = ventura_trading.modify_order(
            app_key=session.app_key,
            client_id=session.client_id,
            auth_token=session.ventura_auth_token,
            order_no=order.broker_order_no,
            quantity=new_quantity,
            order_type=new_order_type,
            price=new_price,
            trigger_price=new_trigger_price,
            validity=new_validity,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach broker: {e}")

    is_success = broker_response.get("status") == "success"
    order.broker_message = broker_response.get("message", order.broker_message)
    order.last_status_check_at = now_ist_naive()

    if not is_success:
        db.commit()
        raise HTTPException(status_code=400, detail=broker_response.get("message", "Broker declined."))

    order.quantity = new_quantity
    order.order_type = new_order_type
    order.price = new_price
    order.trigger_price = new_trigger_price
    order.validity = new_validity
    db.commit()
    db.refresh(order)
    return _serialize_order(order)
