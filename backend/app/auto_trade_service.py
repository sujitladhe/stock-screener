"""
auto_trade_service.py — turns a TRIGGERED auto order into a real order
at Ventura, and records exactly what happened.

Everything here is BLOCKING (database + HTTP), so ws_client.py runs it
in a worker thread (asyncio.to_thread) and the live tick loop never
waits on a broker call. Each function opens its own DB session because
a SQLAlchemy session must not be shared across threads.

HARD RULE (handoff Section 3, #10): the order is placed with the
ORDER OWNER'S OWN Ventura session (their app_key / client_id /
auth_token from their UserSession row) — never the shared service
account. If that user has no active login session, or their token can't
be refreshed, the order is NOT placed; it's recorded as Rejected with
the reason.

SAFETY AGAINST DOUBLE-PLACING
-----------------------------
1. ws_client removes the order from the in-memory registry before
   calling here, so later ticks can't fire it again.
2. The first thing execute_auto_order does is an atomic
   "Active -> Triggering" UPDATE. Only the caller that changes a row
   gets to place the order; a cancel that landed a millisecond earlier
   (status already Cancelled) makes the claim fail and nothing is sent.
3. There is NO automatic retry. If anything about the broker call is
   uncertain (timeout, dropped connection), the order is recorded as
   Rejected with an "UNCONFIRMED ..." message telling the user to check
   Ventura's order book — a blind retry could place a duplicate order
   with real money.
"""

from datetime import timedelta

from sqlalchemy import or_

from app.database import SessionLocal
from app.models import Order, Instrument, now_ist_naive
from app import ventura_trading
from app.session_service import ensure_fresh_token, get_latest_active_session

# A "Triggering" row older than this at engine start means the server
# stopped mid-trigger (a normal trigger finishes in a second or two).
INTERRUPTED_GRACE_SECONDS = 120


def _record_failure(db, order: Order, base: dict, message: str) -> dict:
    order.status = "Rejected"
    order.broker_message = message
    order.last_status_check_at = now_ist_naive()
    db.commit()
    return {**base, "outcome": "failed", "message": message, "broker_order_no": None}


def execute_auto_order(order_id: int, trigger_details: str) -> dict:
    """
    Claims and places one triggered auto order. Returns a dict with
    outcome = "success" | "failed" | "skipped", plus fields the caller
    forwards to the user's browser as a notification.

    "skipped" means someone else got there first (e.g. the user
    cancelled it at the same instant) — nothing was sent to the broker.
    """
    db = SessionLocal()
    try:
        # --- 1. Atomic claim: Active -> Triggering --------------------
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

        # --- 2. The order owner's OWN live session ---------------------
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

        # --- 3. Place it -----------------------------------------------
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
            # Ventura answered with an error status — a definite "no".
            return _record_failure(db, order, base, f"Broker rejected the request: {e}")
        except Exception as e:
            # Timeout / dropped connection: we do NOT know whether the
            # order reached Ventura. Never retry blindly (see module docstring).
            return _record_failure(
                db, order, base,
                f"UNCONFIRMED: no clear answer from the broker ({e}). The order may or may not "
                f"have been placed — check your Ventura order book before placing it again.",
            )

        # --- 4. Record the broker's answer -----------------------------
        is_success = broker_response.get("status") == "success"
        broker_order_no = broker_response.get("order_no")

        order.status = "Pending" if is_success else "Rejected"
        order.broker_order_no = broker_order_no
        order.broker_message = broker_response.get("message")
        order.last_status_check_at = now_ist_naive()
        try:
            db.commit()
        except Exception as e:
            # The broker already has the order; shout, because our own
            # record is now behind reality.
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
    """
    Called when the engine starts. A row still in "Triggering" from a
    previous run means the server stopped between claiming the order
    and recording the broker's answer, so its true state is unknown.
    It's marked Rejected with a message that says so, rather than left
    stuck (and never retried — see module docstring).
    """
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


def prewarm_sessions() -> None:
    """
    Called when the engine starts (before market open on a normal day):
    makes sure every user who has ACTIVE auto orders has a fresh Ventura
    token, so the relogin doesn't have to happen — and can't fail — in
    the middle of the moment an order is triggered. Best-effort: a
    failure is logged, and the trigger-time path will try again.
    """
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
