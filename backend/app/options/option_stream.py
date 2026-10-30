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
"""

import asyncio
import json
import logging
import math
import threading
import time
from datetime import datetime, date
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


def _get_credentials(db_factory) -> tuple:
    """
    Return (auth_token, feed_token, api_key, client_code) by REUSING the
    existing Angel One session stored in the DB by angel_client.py.

    We must NOT call SmartConnect.generateSession() here — doing so creates a
    brand-new JWT which instantly invalidates the token the main screener is
    already using (Angel One only allows one active session per client code).
    The two processes would then keep killing each other's sessions in a loop.

    If no session exists yet we fall back to angel_client.get_valid_jwt_token(),
    which stores the new token for both sides to share.
    """
    from app.models import AngelSession
    from app import angel_client

    with db_factory() as db:
        session_row = db.query(AngelSession).first()
        if session_row and session_row.jwt_token and session_row.feed_token:
            return (
                session_row.jwt_token,
                session_row.feed_token,
                settings.angel_api_key,
                settings.angel_client_code,
            )

        # No session row yet — create one via the shared angel_client helper so
        # both the REST callers and the WS connection share the same token.
        logger.info("No existing Angel One session found — performing fresh login.")
        jwt = angel_client.get_valid_jwt_token(
            db,
            settings.angel_client_code,
            settings.angel_mpin,
            settings.angel_api_key,
            settings.angel_totp_secret,
        )
        session_row = db.query(AngelSession).first()
        feed_token = session_row.feed_token if session_row else None

    if not feed_token:
        raise RuntimeError(
            "Angel One session has no feed_token — ensure the main screener "
            "has logged in at least once before starting the options stream."
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

    while not _stop_event.is_set():
        try:
            auth_token, feed_token, api_key, client_code = _get_credentials(db_factory)

            sws = SmartWebSocketV2(auth_token, api_key, client_code, feed_token)
            _sws_instance = sws

            def on_open(ws, _resp):
                logger.info("Angel One option WS opened")
                with _lock:
                    option_chain_state["connected"] = True

                # Subscribe to NFO options (SnapQuote)
                nfo_token_list  = [{"exchangeType": NFO_EXCHANGE_TYPE, "tokens": tokens}]
                sws.subscribe("opt-chain-1", MODE_SNAPQUOTE, nfo_token_list)

                # Subscribe to NIFTY index spot (LTP only)
                nse_token_list = [{"exchangeType": NSE_EXCHANGE_TYPE,
                                   "tokens": [NIFTY_INDEX_TOKEN]}]
                sws.subscribe("nifty-spot-1", MODE_LTP, nse_token_list)

            def on_data(_ws, message):
                try:
                    _process_tick(message)
                except Exception as e:
                    logger.debug(f"Tick processing error: {e}")

            def on_error(_ws, error):
                logger.warning(f"Angel One option WS error: {error}")
                with _lock:
                    option_chain_state["connected"] = False

            def on_close(_ws):
                logger.info("Angel One option WS closed")
                with _lock:
                    option_chain_state["connected"] = False

            sws.on_open  = on_open
            sws.on_data  = on_data
            sws.on_error = on_error
            sws.on_close = on_close
            sws.connect()  # blocking

        except Exception as exc:
            logger.error(f"WS worker error: {exc}. Reconnecting in 10s…")
            with _lock:
                option_chain_state["connected"] = False
            _stop_event.wait(10)

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
    from datetime import timedelta
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
