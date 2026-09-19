"""
ventura_trading.py — order placement, cancellation, modification,
order book, and positions, via Ventura's EaseAPI.

CRITICAL: every function here takes an `auth_token` (and `client_id`,
`app_key`) parameter explicitly, and the CALLER is responsible for
passing the CURRENT LOGGED-IN USER's own values -- obtained via
get_current_session, from their own UserSession row. NEVER pass the
shared service account's credentials (settings.ventura_service_*)
into any function in this file. Those are used elsewhere for
instruments/live-feed data, which is shared infrastructure -- orders
are real money movement on one specific person's account, and using
the wrong credentials here would be a serious bug, not a cosmetic one.

Endpoint details for EVERY function in this file, including
modify_order(), are now confirmed against Ventura's own published
EaseAPI docs (https://easeapi.venturasecurities.com/docs/) -- not
guessed. modify_order() was originally written before that doc page
was checked; verifying it against the real docs caught one real bug
(the payload was using `disclosed_quantity` where Ventura's API
actually expects `disc_quantity` -- now fixed below). The
MODIFY_ORDER_URL itself turned out to be correct as originally
inferred from the other trade/v1/* endpoints' naming convention.
"""

import requests

DELIVERY_ORDER_URL = "https://easeapi.venturasecurities.com/trade/v1/delivery"
INTRADAY_ORDER_URL = "https://easeapi.venturasecurities.com/trade/v1/intraday/regular"
CANCEL_ORDER_URL = "https://easeapi.venturasecurities.com/trade/v1/cancel"
ORDER_BOOK_URL = "https://easeapi.venturasecurities.com/trade/v1/orders"
POSITIONS_URL = "https://easeapi.venturasecurities.com/portfolio/v1/positions"

MODIFY_ORDER_URL = "https://easeapi.venturasecurities.com/trade/v1/modify"


def _headers(app_key: str, client_id: str, auth_token: str, json_body: bool = True) -> dict:
    headers = {
        "x-client-id": client_id,
        "x-app-key": app_key,
        "authorization": f"Bearer {auth_token}",
    }
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def place_order(
    app_key: str,
    client_id: str,
    auth_token: str,
    order_kind: str,  # "delivery" or "intraday" -- picks the endpoint
    instrument_id: int,
    exchange: str,
    segment: str,
    transaction_type: str,  # "B" or "S"
    order_type: str,  # "MKT", "LMT", "SL", "SLM"
    quantity: int,
    product: str,  # "C", "I", "M", "F"
    price: float = 0.0,
    trigger_price: float = 0.0,
    validity: str = "DAY",
    disclosed_quantity: int = 0,
    off_market_flag: int = 0,
) -> dict:
    """
    Places a real order on the user's Ventura account. Returns the
    parsed JSON response: {client_id, security_id, order_no, status,
    message} -- status is "success" or "error" (per Ventura's exact
    wording, confirmed from their docs).

    Raises RuntimeError only for transport-level failures (bad status
    code, unparseable response) -- a broker-side REJECTION still comes
    back as a normal 200 response with status="error", which the
    caller must check explicitly rather than relying on an exception.
    """
    if order_kind == "delivery":
        url = DELIVERY_ORDER_URL
    elif order_kind == "intraday":
        url = INTRADAY_ORDER_URL
    else:
        raise ValueError(f"order_kind must be 'delivery' or 'intraday', got {order_kind!r}")

    payload = {
        "instrument_id": instrument_id,
        "exchange": exchange,
        "segment": segment,
        "transaction_type": transaction_type,
        "order_type": order_type,
        "quantity": quantity,
        "price": price,
        "trigger_price": trigger_price,
        "product": product,
        "validity": validity,
        "disclosed_quantity": disclosed_quantity,
        "off_market_flag": off_market_flag,
    }

    response = requests.post(url, headers=_headers(app_key, client_id, auth_token), json=payload, timeout=15)

    if response.status_code != 200:
        raise RuntimeError(f"Order placement request failed (HTTP {response.status_code}): {response.text}")

    return response.json()


def cancel_order(app_key: str, client_id: str, auth_token: str, order_no: str) -> dict:
    """Returns {client_id, order_no, message, status} per Ventura's docs."""
    response = requests.post(
        CANCEL_ORDER_URL,
        headers=_headers(app_key, client_id, auth_token),
        json={"order_no": order_no},
        timeout=15,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Cancel order request failed (HTTP {response.status_code}): {response.text}")
    return response.json()


def modify_order(
    app_key: str,
    client_id: str,
    auth_token: str,
    order_no: str,
    quantity: int,
    order_type: str,
    price: float = 0.0,
    trigger_price: float = 0.0,
    validity: str = "DAY",
    disc_quantity: int = 0,
) -> dict:
    """
    Modifies a still-open (Pending) order. Per Ventura's docs, this
    resends the full order (not just changed fields) -- the router
    calling this fills in the order's CURRENT stored values for
    anything the user didn't change, rather than sending partial data.

    Returns {client_id, order_no, message, status} per Ventura's docs
    -- status is "success" or "error", same convention as place_order
    and cancel_order.
    """
    payload = {
        "order_no": order_no,
        "quantity": quantity,
        "order_type": order_type,
        "price": price,
        "trigger_price": trigger_price,
        "validity": validity,
        "disc_quantity": disc_quantity,
    }

    response = requests.post(
        MODIFY_ORDER_URL,
        headers=_headers(app_key, client_id, auth_token),
        json=payload,
        timeout=15,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Modify order request failed (HTTP {response.status_code}): {response.text}")
    return response.json()


def get_order_book(app_key: str, client_id: str, auth_token: str) -> list:
    """
    Returns today's orders only -- Ventura's own docs state the order
    book is retained for a single day. Each item includes `status`
    ("Pending"/"Executed"/"Cancelled"/"Rejected", etc. -- exact string
    from the broker) and `order_id` matching what we stored as
    broker_order_no when the order was placed.
    """
    response = requests.get(ORDER_BOOK_URL, headers=_headers(app_key, client_id, auth_token, json_body=False), timeout=15)
    if response.status_code != 200:
        raise RuntimeError(f"Order book request failed (HTTP {response.status_code}): {response.text}")
    body = response.json()
    return body.get("result") or []


def get_positions(app_key: str, client_id: str, auth_token: str) -> dict:
    """
    Returns {"open_positions": [...], "closed_positions": [...]} --
    each position already includes `profit_loss`, computed by the
    broker itself. We deliberately do NOT recompute P&L ourselves from
    live ticks; the broker's own figure is authoritative and avoids an
    entire class of potential bugs in a from-scratch P&L engine.

    Confirmed field names per position, per Ventura's docs: `symbol`,
    `token`, `last_traded_price`, `exchange`, `segment`, `action`
    ("B"/"S" per the docs' own parameter table -- note their sample
    response instead shows literal "BUY"/"SELL", an inconsistency in
    Ventura's own docs, so the frontend doesn't rely on this field's
    exact string), `product_type`, `average_traded_price`,
    `total_quantity` (SIGNED -- negative means a short/sell position,
    positive means long/buy), `profit_loss`, `lot_size`, plus
    F&O-only fields (instrument_type, expiry_date, expiry_type,
    option_type, strike_price) that are empty strings for equity.
    """
    response = requests.get(POSITIONS_URL, headers=_headers(app_key, client_id, auth_token, json_body=False), timeout=15)
    if response.status_code != 200:
        raise RuntimeError(f"Positions request failed (HTTP {response.status_code}): {response.text}")
    body = response.json()
    return body.get("result") or {"open_positions": [], "closed_positions": []}
