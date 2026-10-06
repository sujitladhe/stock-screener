"""
auto_trade_service.py — turns a TRIGGERED auto order into a real order
at Ventura, and records exactly what happened.

New in 0004: expire_daily_auto_orders() — cancels Active "today only"
orders from previous trading days. Called at engine start alongside
recover_interrupted_orders().
"""

from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_

from app.database import SessionLocal
from app.models import Order, Instrument, now_ist_naive
from app import ventura_trading
from app.session_service import ensure_fresh_token, get_latest_active_session

IST = ZoneInfo("Asia/Kolkata")

INTERRUPTED_GRACE_SECONDS = 120


def _record_failure(db, order: Order, base: dict, message: str) -> dict:
    order.status = "Rejected"
    order.broker_message = message
    order.last_status_check_at = now_ist_naive()
    db.commit()
    return {**base, "outcome": "failed", "message": message, "broker_order_no": None}


def execute_auto_order(order_id: int, trigger_details: str) -> dict:
    db = SessionLocal()
    try:
        claimed = (
            db.query(Order)
            .filter(Order.id == order_id, Order.source == "auto", Order.status == "Active")
            .update(
                {
                    "status": "Triggering",
                    "triggered_at": now_ist_naive(),
                    "trigger_details": trigger_details,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        if not claimed:
            return {
                "outcome": "skipped",
                "order_id": order_id,
                "message": "Order was no longer Active (cancelled or already handled).",
            }

        order = db.query(Order).filter_by(id=order_id).first()
        base = {
            "order_id": order.id,
            "client_id": order.client_id,
            "trading_symbol": order.trading_symbol,
            "transaction_type": order.transaction_type,
            "quantity": order.quantity,
            "trigger_details": trigger_details,
        }

        session_row = get_latest_active_session(db, order.client_id)
        if session_row is None:
            return _record_failure(
                db, order, base,
                "Not placed: no active login session for this account when the condition "
                "matched (you had logged out). Log in and create the auto order again.",
            )
        try:
            ensure_fresh_token(db, session_row)
        except Exception as e:
            return _record_failure(
                db, order, base,
                f"Not placed: could not refresh your Ventura login before placing the order ({e}).",
            )

        instrument = db.query(Instrument).filter_by(id=order.instrument_id).first()
        if instrument is None:
            return _record_failure(db, order, base, "Not placed: the instrument no longer exists.")

        try:
            broker_response = ventura_trading.place_order(
                app_key=session_row.app_key,
                client_id=session_row.client_id,
                auth_token=session_row.ventura_auth_token,
                order_kind=order.order_kind,
                instrument_id=int(instrument.exchange_token),
                exchange="NSE",
                segment="E",
                transaction_type=order.transaction_type,
                order_type=order.order_type,
                quantity=order.quantity,
                product=order.product,
                price=float(order.price or 0),
                trigger_price=float(order.trigger_price or 0),
                validity=order.validity,
            )
        except RuntimeError as e:
            return _record_failure(db, order, base, f"Broker rejected the request: {e}")
        except Exception as e:
            return _record_failure(
                db, order, base,
                f"UNCONFIRMED: no clear answer from the broker ({e}). The order may or may not "
                f"have been placed — check your Ventura order book before placing it again.",
            )

        is_success = broker_response.get("status") == "success"
        broker_order_no = broker_response.get("order_no")

        order.status = "Pending" if is_success else "Rejected"
        order.broker_order_no = broker_order_no
        order.broker_message = broker_response.get("message")
        order.last_status_check_at = now_ist_naive()
        try:
            db.commit()
        except Exception as e:
            print(f"[auto_trade_service] !!! Order {order.id} was PLACED at the broker "
                  f"(order_no={broker_order_no}, success={is_success}) but saving the result failed: {e}")
            db.rollback()

        return {
            **base,
            "outcome": "success" if is_success else "failed",
            "message": broker_response.get("message"),
            "broker_order_no": broker_order_no,
        }
    finally:
        db.close()


def recover_interrupted_orders() -> int:
    db = SessionLocal()
    try:
        cutoff = now_ist_naive() - timedelta(seconds=INTERRUPTED_GRACE_SECONDS)
        stuck = (
            db.query(Order)
            .filter(
                Order.source == "auto",
                Order.status == "Triggering",
                or_(Order.triggered_at.is_(None), Order.triggered_at < cutoff),
            )
            .all()
        )
        for order in stuck:
            order.status = "Rejected"
            order.broker_message = (
                "UNCONFIRMED: the server stopped while this auto order was being placed. It may or may "
                "not have reached Ventura — check your Ventura order book before placing it again."
            )
            order.last_status_check_at = now_ist_naive()
        db.commit()
        return len(stuck)
    finally:
        db.close()


def expire_daily_auto_orders() -> int:
    """
    Called at engine start. Cancels Active 'today only' (auto_expires_daily=True)
    auto orders whose creation date (placed_at IST) is before today. These orders
    were set to expire at the end of yesterday's session.

    This does NOT affect orders created today — a 'today only' order placed at
    09:00 is still Active and should fire if it can before 15:30.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    db = SessionLocal()
    try:
        today_ist = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        # placed_at is IST-naive, so .date() comparison works correctly
        candidates = (
            db.query(Order)
            .filter(
                Order.source == "auto",
                Order.status == "Active",
                Order.auto_expires_daily == True,  # noqa: E712
            )
            .all()
        )
        count = 0
        for order in candidates:
            if order.placed_at.date() < today_ist:
                order.status = "Cancelled"
                order.broker_message = (
                    "Today-only auto order expired — was not triggered before market close."
                )
                order.last_status_check_at = now_ist_naive()
                count += 1
        db.commit()
        return count
    finally:
        db.close()


def prewarm_sessions() -> None:
    db = SessionLocal()
    try:
        client_ids = [
            row[0]
            for row in db.query(Order.client_id)
            .filter(Order.source == "auto", Order.status == "Active")
            .distinct()
            .all()
        ]
        for client_id in client_ids:
            session_row = get_latest_active_session(db, client_id)
            if session_row is None:
                print(f"[auto_trade_service] {client_id} has active auto orders but no active login "
                      f"session — those orders will fail if they trigger.")
                continue
            try:
                ensure_fresh_token(db, session_row)
                print(f"[auto_trade_service] Session for {client_id} is ready for auto trade.")
            except Exception as e:
                print(f"[auto_trade_service] Could not pre-refresh session for {client_id}: {e}")
    finally:
        db.close()
