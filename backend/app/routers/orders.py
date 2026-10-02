"""
routers/orders.py — order placement and management.

Every endpoint here uses get_current_session, giving us the CURRENT
LOGGED-IN USER's own app_key/client_id/auth_token -- orders are placed
on that specific person's Ventura account, never the shared service
account used elsewhere in this app for instruments/market data.

Covers: placement, listing (our own permanent record, synced against
the broker's live order book for today's still-open orders, since
Ventura's own Order Book only retains the current day), cancellation,
and modification. record_and_place_order() is exported so
routers/positions.py can place a stoploss exit order (and the frontend's
"Exit position" button, which is just a normal opposite-direction
order) against a running position through the exact same path (same DB
bookkeeping, same broker-credential rule) instead of duplicating this
logic, and so a "reorder a cancelled order" flow on the frontend is
just a normal POST /orders/place with the old order's values
pre-filled -- not a special server-side path.

AUTO TRADE (requirement 10): POST /orders/auto saves an order that the
live engine will place BY ITSELF once its volume / green-candle
condition is met (see app/auto_trade_engine.py). It's stored in the
same `orders` table with source="auto" and status "Active" until it
fires, so the list, cancel and status-sync code below serve both kinds.
GET /orders takes ?source=manual|auto|all for the Orders page dropdown.

EDITING A STILL-ACTIVE AUTO ORDER (new): PATCH /orders/{id}/auto lets
the owner change a saved-but-not-yet-triggered auto order's quantity,
order type, price/trigger, and its trigger conditions -- in place, same
id and placed_at, since nothing has been sent to the broker yet. This
is deliberately a SEPARATE endpoint from PATCH /orders/{id}/modify,
which is for a Pending order already sitting with the broker (a
totally different operation -- Ventura's modify call, not a plain DB
update) and only ever touches quantity/price/trigger/validity, never
the auto-trigger fields an Active order still has.

All stored timestamps use now_ist_naive() (see models.py) instead of
datetime.utcnow() -- a real bug had order placement times displayed
~5.5 hours off Indian time because this file used UTC while the rest
of the app follows IST discipline.
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

# Statuses we already know are final -- no point spending a broker API
# call re-checking these on every /orders listing request.
# ("Active" and "Triggering" are auto-trade states and are NOT final.)
TERMINAL_STATUSES = {"Executed", "Cancelled", "Rejected"}

VALID_SOURCES = {"manual", "auto", "all"}
VALID_ORDER_TYPES = {"MKT", "LMT", "SL", "SLM"}
VALID_VALIDITIES = {"DAY", "IOC"}
# Same order-kind <-> product pairing the order forms enforce (handoff
# Section 3, #12). Checked again server-side for AUTO orders because
# they're sent unattended, later, with nobody watching the response.
PRODUCTS_BY_KIND = {"delivery": {"C"}, "intraday": {"I", "M"}}


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


class CreateAutoOrderRequest(PlaceOrderRequest):
    """
    A normal order definition PLUS the condition that should release it.
    At least one of volume_threshold / candle_pct_threshold is required.
    Also reused, unchanged, as the request body for PATCH .../auto
    (editing a still-Active auto order sends this same full shape).
    """
    # Volume value (volume x price) in RAW RUPEES. The frontend converts
    # what the user types in crores (6 -> 60000000) before sending, per
    # architecture principle #9 (scaling lives only in the UI layer).
    volume_threshold: Optional[float] = None
    # Current 1-minute candle % change (green candles only).
    candle_pct_threshold: Optional[float] = None
    # "AND" / "OR" -- required only when BOTH thresholds are given.
    combinator: Optional[str] = None
    # Optional "HH:MM" IST cut-off. After it, the order won't trigger
    # that day; it stays active and is checked again the next trading day.
    valid_till: Optional[str] = None


class ModifyOrderRequest(BaseModel):
    # All optional -- only fields the user actually changed need to be
    # sent. Anything omitted is filled in from the order's current
    # stored values before calling the broker (see modify_order()
    # below), since Ventura's modify call is assumed to need the full
    # order resent, not just a diff.
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
        # --- auto trade ---
        "source": o.source or "manual",
        # Raw rupees, exactly as stored -- the Orders page converts to crores for display.
        "auto_volume_threshold": float(o.auto_volume_threshold) if o.auto_volume_threshold is not None else None,
        "auto_candle_pct_threshold": float(o.auto_candle_pct_threshold) if o.auto_candle_pct_threshold is not None else None,
        "auto_combinator": o.auto_combinator,
        "auto_valid_till": o.auto_valid_till.strftime("%H:%M") if o.auto_valid_till else None,
        "triggered_at": o.triggered_at.isoformat() if o.triggered_at else None,
        "trigger_details": o.trigger_details,
    }


def _parse_valid_till(value: Optional[str]) -> Optional[dtime]:
    """
    'HH:MM' -> time, or None if blank. Raises 400 if malformed / outside
    market hours. Valid-till is MINUTE precision: if a client ever sends
    seconds ('HH:MM:SS') they are dropped, and the order is treated as
    valid through the whole of that minute (09:30 -> until 09:30:59).
    """
    if value is None or not value.strip():
        return None
    text = value.strip()
    try:
        parts = [int(p) for p in text.split(":")]
        if len(parts) not in (2, 3):
            raise ValueError
        parsed = dtime(parts[0], parts[1])  # seconds, if any, deliberately ignored
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="valid_till must be a time like 09:30 (24-hour, IST).")

    if parsed < MARKET_OPEN or parsed > MARKET_CLOSE:
        raise HTTPException(
            status_code=400,
            detail="valid_till must be between 09:15 and 15:30 (IST) -- the order is only ever checked during market hours.",
        )
    return parsed


def _validate_auto_order(req: CreateAutoOrderRequest) -> Optional[dtime]:
    """
    Validates everything about an auto order up front, because it will
    be sent later (or resent, on an edit) with nobody watching. Returns
    the parsed valid_till. Shared by create AND edit-in-place.
    """
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
            detail=f"product '{req.product}' isn't valid for a {req.order_kind} order "
                   f"(allowed: {sorted(PRODUCTS_BY_KIND[req.order_kind])}).",
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
        raise HTTPException(
            status_code=400,
            detail="candle_pct_threshold must be greater than 0 (only green candles are tracked).",
        )
    if req.volume_threshold is not None and req.candle_pct_threshold is not None:
        if req.combinator not in ("AND", "OR"):
            raise HTTPException(status_code=400, detail="combinator must be 'AND' or 'OR' when both conditions are set.")

    return _parse_valid_till(req.valid_till)


def _lookup_tradeable_instrument(db: Session, trading_symbol: str) -> Instrument:
    """
    Shared by create_auto_order and update_auto_order: the symbol must
    be a known, active NSE/EQ instrument AND already have a computed
    average volume (the same universe the live engine/screener scans),
    or an auto order on it could never trigger.
    """
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
            detail=f"{instrument.trading_symbol} isn't in the live feed yet (no average volume has been "
                   f"computed for it), so an auto order on it could never trigger.",
        )
    return instrument


def _sync_todays_open_orders_with_broker(db: Session, session: UserSession) -> None:
    """
    For any of THIS user's orders placed today that we don't already
    know are in a terminal state, ask the broker's own Order Book for
    its current status and update our row. Only today's orders are
    checked -- per ventura_trading.get_order_book's docstring, the
    broker itself only retains the current day, so there's nothing to
    reconcile for older orders (their status is frozen at whatever we
    last recorded, by design -- see the Order model's docstring).

    "Today's" is judged by when the order reached the BROKER: for an
    auto order that is triggered_at (it may have been created days
    earlier), for a manual order it's placed_at. Auto orders that are
    still waiting (Active) or mid-trigger have no broker_order_no yet
    and are skipped here.

    Best-effort: if the broker call itself fails (network blip, broker
    down), we leave existing rows untouched rather than raising --
    stale-but-present data beats a broken listing page.
    """
    today = now_ist_naive().date()
    open_orders = (
        db.query(Order)
        .filter(
            Order.client_id == session.client_id,
            Order.status.notin_(TERMINAL_STATUSES),
        )
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
        return  # best-effort -- see docstring above

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
    """
    Shared "look up instrument, call broker, persist an Order row"
    logic -- used by POST /orders/place below, by routers/positions.py's
    stoploss-exit endpoint, and by the frontend's "Exit position" button
    (which is just POST /orders/place with the opposite transaction_type
    and no trigger), so every kind of order placed through this app gets
    identical handling (same audit trail, same rejection bookkeeping)
    rather than several drifting implementations.

    Raises HTTPException on any validation or broker-level failure, so
    callers can just let it propagate.
    """
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
    source: str = Query(default="all", description="manual | auto | all"),
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    """
    Every order this user has ever placed through this app -- our own
    permanent record (requirement 6c), since Ventura's Order Book only
    keeps today's. Today's still-open orders are refreshed against the
    broker first, so "Open" here reflects real-time broker status, not
    just what we recorded at placement time.

    source (requirement 10f): "manual" = only orders the user placed by
    hand, "auto" = only auto-trade orders (waiting, triggered, failed
    or cancelled), "all" = both. An empty list when there are none.
    """
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
    """
    Saves an AUTO order (requirement 10). Nothing is sent to the broker
    now -- the live engine places it later, by itself, using this
    user's own Ventura session, the first time its condition is met
    inside market hours (and before valid_till, if one was set).

    Allowed at any time, including outside market hours (10d): the
    engine simply starts checking at the next market open.
    """
    valid_till = _validate_auto_order(req)
    instrument = _lookup_tradeable_instrument(db, req.trading_symbol)

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
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    # Hand it to the running engine right away (a no-op if the engine
    # isn't running yet -- it reloads every Active auto order from the
    # database when it starts).
    auto_trade_registry.add_order(order)

    return _serialize_order(order)


@router.patch("/{order_id}/auto")
def update_auto_order(
    order_id: int,
    req: CreateAutoOrderRequest,
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    """
    Edits a still-Active auto order IN PLACE -- same id and placed_at,
    since nothing has been sent to the broker yet. Lets the owner change
    everything: quantity, order type, price/trigger, kind/product, and
    the trigger conditions themselves (volume value, candle %, AND/OR,
    valid-till).

    Uses a conditional UPDATE (status must still be 'Active' at write
    time), the same guard cancel_order() below uses -- if the live
    engine claims this exact order to fire it in the instant between
    this request's read and its write, the edit is rejected with a 409
    instead of silently overwriting whatever the engine just recorded.
    """
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
            detail=f"Only a still-waiting (Active) auto order can be edited this way (this one is {order.status}).",
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
            detail="This auto order triggered at the same moment and could no longer be edited. Refresh to see its status.",
        )

    db.refresh(order)
    auto_trade_registry.add_order(order)  # refresh the engine's in-memory copy with the new conditions

    return _serialize_order(order)


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

    An AUTO order that hasn't triggered yet (status Active) was never
    sent to the broker, so cancelling it is purely local: mark it
    Cancelled and take it out of the live engine's registry.
    """
    order = db.query(Order).filter_by(id=order_id, client_id=session.client_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    if order.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=400, detail=f"Order is already {order.status.lower()} — cannot cancel.")

    if order.source == "auto" and order.status == "Triggering":
        raise HTTPException(
            status_code=409,
            detail="This auto order has just triggered and is being placed right now. "
                   "Refresh in a moment — if it was placed, you can cancel it then.",
        )

    if order.source == "auto" and order.status == "Active":
        # Conditional update: only cancels if it's STILL Active. If the
        # engine claimed it a split second ago, this changes nothing and
        # we say so, instead of pretending the cancel worked.
        changed = (
            db.query(Order)
            .filter(Order.id == order.id, Order.status == "Active")
            .update(
                {
                    "status": "Cancelled",
                    "broker_message": "Auto order cancelled by you before it triggered.",
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
                detail="This auto order triggered at the same moment and could not be cancelled here. "
                       "Refresh to see its status.",
            )
        db.refresh(order)
        return {
            "id": order.id,
            "status": order.status,
            "message": order.broker_message,
        }

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
    order.last_status_check_at = now_ist_naive()
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


@router.patch("/{order_id}/modify")
def modify_order(
    order_id: int,
    req: ModifyOrderRequest,
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    """
    Modifies a still-pending order, via Ventura's confirmed
    trade/v1/modify endpoint (see ventura_trading.modify_order).

    Only fields present in the request are changed; everything else is
    resent as-is from the order's current stored values, since
    Ventura's modify calls (like most brokers') are assumed to expect
    the full order, not a partial diff.

    An auto order that is still waiting (Active) can't be modified here
    -- it has no broker order yet, so PATCH /orders/{id}/auto (above)
    is what the frontend uses for that instead.
    """
    order = db.query(Order).filter_by(id=order_id, client_id=session.client_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    if order.status != "Pending":
        raise HTTPException(status_code=400, detail=f"Only a Pending order can be modified (this one is {order.status}).")

    if not order.broker_order_no:
        raise HTTPException(status_code=400, detail="Order has no broker order number — nothing to modify at the broker.")

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
        raise HTTPException(status_code=400, detail=broker_response.get("message", "Broker declined to modify this order."))

    order.quantity = new_quantity
    order.order_type = new_order_type
    order.price = new_price
    order.trigger_price = new_trigger_price
    order.validity = new_validity
    db.commit()
    db.refresh(order)

    return _serialize_order(order)
