"""
Angel One WebSocket 2.0 option chain stream.

Architecture:
  - A single background thread runs the SmartWebSocketV2 connection.
  - Incoming ticks update the shared `option_chain_state` dict (thread-safe via lock).
  - A separate asyncio task (started from FastAPI lifespan) broadcasts the state
    to all connected frontend WebSocket clients every 1.5 seconds.

Usage (called from router.py lifespan):
    stream.start_stream(tokens, strike_map, db_factory)
    stream.stop_stream()

FIXES in this version:
  - Stale login token: the stored Angel One session is now checked for age,
    and a fresh login is forced when it is old OR when the previous
    connection attempt died before ever opening.
  - Subscription correlation IDs shortened to <= 10 characters.
  - Tokens are subscribed in small batches.
  - on_open accepts 1 or 2 arguments (different SDK versions differ).
  - A pause between reconnect attempts so it can never spin in a tight loop.
  - Real error details are logged instead of just "Connection closed".
"""

import asyncio
import json
import logging
import math
import threading
import time
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Set
from sqlalchemy.orm import Session

import pyotp
from SmartApi import SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2

from app.config import settings
from app.options.models import OptionEodSnapshot

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared in-memory option chain state
# ---------------------------------------------------------------------------
# All writes come from the WS thread; reads from the broadcast asyncio task.
# The lock guards every mutation.

_lock = threading.Lock()

option_chain_state: Dict = {
    "connected":  False,
    "spot":       0.0,
    "timestamp":  None,
    "expiry":     None,          # nearest expiry ISO string
    "atm":        0,
    # {strike: {"ce": {...}, "pe": {...}}}
    "strikes":    {},
    # {token: prev_oi} — loaded from yesterday's EOD snapshot at startup
    "prev_oi":    {},
    # guidance result — updated every 12 seconds by guidance.py
    "guidance":   None,
}

# Strike map: {token → {strike, option_type, expiry, lot_size}}
_strike_map: Dict = {}

# ---------------------------------------------------------------------------
# Angel One auth
# ---------------------------------------------------------------------------
NIFTY_INDEX_TOKEN = "26000"   # NSE:NIFTY 50 index
NFO_EXCHANGE_TYPE = 2          # Angel One enum for NFO
NSE_EXCHANGE_TYPE = 1          # Angel One enum for NSE
MODE_LTP         = 1
MODE_SNAPQUOTE   = 3

# A stored Angel One login older than this is treated as stale and replaced.
MAX_SESSION_AGE = timedelta(hours=6)

# How many option tokens to send per subscribe message.
SUBSCRIBE_BATCH_SIZE = 200

# Seconds to wait between connection attempts.
RECONNECT_PAUSE_SECONDS = 10


def _session_is_stale(session_row) -> bool:
    """True if the stored Angel One login is missing, incomplete or too old."""
    if not session_row or not session_row.jwt_token or not session_row.feed_token:
        return True
    if not session_row.logged_in_at:
        return True
    # logged_in_at is stored with datetime.utcnow() in angel_client.py
    return (datetime.utcnow() - session_row.logged_in_at) > MAX_SESSION_AGE


def _get_credentials(db_factory, force_fresh: bool = False) -> tuple:
    """
    Return (auth_token, feed_token, api_key, client_code).

    Reuses the Angel One session stored in the DB by angel_client.py so we do
    NOT fight with the rest of the app (Angel One allows one active session per
    client code). BUT the stored session is only reused when it is recent.
    If it is old/missing, or force_fresh is True (the last connection attempt
    failed before opening), we log in again through the shared angel_client
    helper, which stores the new token for everyone to share.
    """
    from app.models import AngelSession
    from app import angel_client

    with db_factory() as db:
        session_row = db.query(AngelSession).first()

        if force_fresh or _session_is_stale(session_row):
            logger.info(
                "Angel One session is stale/missing or last attempt failed — "
                "performing a fresh login."
            )
            session_row = angel_client._login_and_store(
                db,
                settings.angel_client_code,
                settings.angel_mpin,
                settings.angel_api_key,
                settings.angel_totp_secret,
            )

        jwt = session_row.jwt_token
        feed_token = session_row.feed_token

    if not jwt or not feed_token:
        raise RuntimeError(
            "Angel One login did not return a jwt_token / feed_token."
        )

    return jwt, feed_token, settings.angel_api_key, settings.angel_client_code


# ---------------------------------------------------------------------------
# Tick processing
# ---------------------------------------------------------------------------

def _ltp_from_paise(paise: int) -> float:
    return round(paise / 100, 2)


def _process_tick(message: dict) -> None:
    """Update option_chain_state from a single WebSocket tick."""
    token      = str(message.get("token", ""))
    raw_ltp    = message.get("last_traded_price", 0)
    raw_oi     = message.get("open_interest", 0)
    raw_volume = message.get("volume_trade_for_the_day", 0)
    ltp        = _ltp_from_paise(raw_ltp)

    # NIFTY spot index tick
    if token == NIFTY_INDEX_TOKEN:
        with _lock:
            option_chain_state["spot"] = ltp
            option_chain_state["timestamp"] = datetime.utcnow().isoformat()
        return

    info = _strike_map.get(token)
    if not info:
        return

    strike     = info["strike"]
    opt_type   = info["option_type"].lower()   # "ce" or "pe"
    expiry_iso = info["expiry"]
    prev_oi    = option_chain_state["prev_oi"].get(token, 0)
    oi_chg_pct = (
        ((raw_oi - prev_oi) / prev_oi * 100) if prev_oi > 0 else 0.0
    )
    voi = round(raw_volume / raw_oi, 3) if raw_oi > 0 else 0.0

    with _lock:
        if strike not in option_chain_state["strikes"]:
            option_chain_state["strikes"][strike] = {"ce": None, "pe": None}
        option_chain_state["strikes"][strike][opt_type] = {
            "ltp":        ltp,
            "oi":         raw_oi,
            "oi_chg_pct": round(oi_chg_pct, 2),
            "volume":     raw_volume,
            "voi":        voi,
            "expiry":     expiry_iso,
            "token":      token,
        }
        # Keep nearest expiry on state for the guidance engine
        if not option_chain_state["expiry"]:
            option_chain_state["expiry"] = expiry_iso


# ---------------------------------------------------------------------------
# WebSocket thread
# ---------------------------------------------------------------------------

_ws_thread:    Optional[threading.Thread] = None
_stop_event    = threading.Event()
_sws_instance: Optional[SmartWebSocketV2] = None


def _ws_worker(tokens: List[str], db_factory) -> None:
    """Runs in a daemon thread. Reconnects on error."""
    global _sws_instance

    # After a failed attempt (connection never opened) we force a fresh login
    # next time, because the most common cause is an expired token.
    force_fresh = False

    while not _stop_event.is_set():
        opened = {"value": False}
        try:
            auth_token, feed_token, api_key, client_code = _get_credentials(
                db_factory, force_fresh=force_fresh
            )

            sws = SmartWebSocketV2(auth_token, api_key, client_code, feed_token)
            _sws_instance = sws

            def on_open(ws, *_args):
                logger.info("Angel One option WS opened")
                opened["value"] = True
                with _lock:
                    option_chain_state["connected"] = True

                # Subscribe to NFO options (SnapQuote) in small batches.
                # Correlation IDs must be 10 characters or fewer.
                for n, i in enumerate(range(0, len(tokens), SUBSCRIBE_BATCH_SIZE)):
                    batch = tokens[i:i + SUBSCRIBE_BATCH_SIZE]
                    nfo_token_list = [{"exchangeType": NFO_EXCHANGE_TYPE, "tokens": batch}]
                    sws.subscribe(f"optchn{n:03d}", MODE_SNAPQUOTE, nfo_token_list)
                    time.sleep(0.2)

                # Subscribe to NIFTY index spot (LTP only)
                nse_token_list = [{"exchangeType": NSE_EXCHANGE_TYPE,
                                   "tokens": [NIFTY_INDEX_TOKEN]}]
                sws.subscribe("niftyspot", MODE_LTP, nse_token_list)
                logger.info(f"Subscribed to {len(tokens)} option tokens + NIFTY spot.")

            def on_data(_ws, message, *_args):
                try:
                    _process_tick(message)
                except Exception as e:
                    logger.debug(f"Tick processing error: {e}")

            def on_error(_ws, *args):
                logger.warning(f"Angel One option WS error: {args}")
                with _lock:
                    option_chain_state["connected"] = False

            def on_close(_ws, *args):
                logger.info("Angel One option WS closed")
                with _lock:
                    option_chain_state["connected"] = False

            sws.on_open  = on_open
            sws.on_data  = on_data
            sws.on_error = on_error
            sws.on_close = on_close
            sws.connect()  # blocking

            # connect() returned: the connection ended.
            with _lock:
                option_chain_state["connected"] = False

            if opened["value"]:
                # It worked for a while, so the token was fine. Just reconnect
                # (the age check will refresh the token if it has become old).
                force_fresh = False
            else:
                # Never opened -> almost certainly a rejected/expired token.
                logger.warning("Option WS never opened — will log in fresh on next attempt.")
                force_fresh = True

        except Exception as exc:
            logger.error(f"WS worker error: {exc}. Retrying in {RECONNECT_PAUSE_SECONDS}s…")
            with _lock:
                option_chain_state["connected"] = False
            force_fresh = True

        # Always pause before the next attempt (never spin in a tight loop).
        _stop_event.wait(RECONNECT_PAUSE_SECONDS)

    logger.info("WS worker stopped.")


# ---------------------------------------------------------------------------
# Public API — called from router lifespan
# ---------------------------------------------------------------------------

def load_strike_map(strike_map: dict) -> None:
    """Called once at startup with the token→strike mapping from DB."""
    global _strike_map
    _strike_map = strike_map


def load_prev_oi(db: Session) -> None:
    """
    Load yesterday's EOD OI per token into option_chain_state["prev_oi"].
    Required for OI change % calculation during the session.
    Call this while a valid DB session is open.
    """
    yesterday = date.today() - timedelta(days=1)

    rows = (
        db.query(OptionEodSnapshot)
        .filter(OptionEodSnapshot.date == yesterday)
        .all()
    )

    # Build {token: oi} using strike_map in reverse
    # Reverse map: {(strike, option_type, expiry_iso) → token}
    reverse = {
        (v["strike"], v["option_type"], v["expiry"]): tok
        for tok, v in _strike_map.items()
    }

    prev: Dict[str, int] = {}
    for row in rows:
        expiry_iso = row.expiry.isoformat()
        ce_tok = reverse.get((row.strike, "CE", expiry_iso))
        pe_tok = reverse.get((row.strike, "PE", expiry_iso))
        if ce_tok and row.ce_oi:
            prev[ce_tok] = row.ce_oi
        if pe_tok and row.pe_oi:
            prev[pe_tok] = row.pe_oi

    with _lock:
        option_chain_state["prev_oi"] = prev

    logger.info(f"Loaded prev-OI for {len(prev)} tokens from {yesterday}")


def start_stream(tokens: List[str], strike_map: dict, db_factory) -> None:
    """
    Start the WebSocket background thread.
    Accepts db_factory (a callable that returns a context-managed Session)
    so the thread can open fresh sessions as needed — not a closed db instance.
    """
    global _ws_thread
    if _ws_thread and _ws_thread.is_alive():
        logger.info("Option stream already running.")
        return

    load_strike_map(strike_map)

    _stop_event.clear()
    _ws_thread = threading.Thread(
        target=_ws_worker, args=(tokens, db_factory), daemon=True, name="option-ws"
    )
    _ws_thread.start()
    logger.info("Option stream thread started.")


def stop_stream() -> None:
    """Signal the WebSocket thread to stop."""
    _stop_event.set()
    if _sws_instance:
        try:
            _sws_instance.close_connection()
        except Exception:
            pass
    logger.info("Option stream stop requested.")


# ---------------------------------------------------------------------------
# Snapshot helpers (used by broadcast and EOD job)
# ---------------------------------------------------------------------------

def get_snapshot() -> dict:
    """Thread-safe copy of the current option chain state."""
    with _lock:
        import copy
        return copy.deepcopy(option_chain_state)


def update_guidance(result: dict) -> None:
    """Called by the guidance runner to push latest engine result."""
    with _lock:
        option_chain_state["guidance"] = result
