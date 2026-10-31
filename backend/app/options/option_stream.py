"""
Angel One WebSocket 2.0 option chain stream.

Architecture:
  - A single background thread runs the SmartWebSocketV2 connection.
  - Incoming ticks update the shared `option_chain_state` dict (thread-safe via lock).
  - The router's asyncio tasks read that state (broadcast to browsers, 1-minute
    history snapshots for the guidance engine).

Changes in this version:
  - ONLY THE NEAREST EXPIRY is subscribed and tracked. Before, two expiries
    shared one table keyed by strike, so their ticks overwrote each other and
    the numbers jumped around.
  - Previous-day OI now comes from the 1-minute history table (the old cron
    EOD job ran in a separate process with an empty memory).
  - reset_state() / stop_stream(wait=True) so the router can restart the stream
    for a new trading day.
  - (kept) fresh Angel One login when the stored token is stale; short
    subscription IDs; batched subscriptions; pause between reconnects.
"""

import logging
import threading
import time
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from SmartApi.smartWebSocketV2 import SmartWebSocketV2

from app.config import settings
from app.models import now_ist_naive
from app.options.models import OptionEodSnapshot, OptionMinuteSnapshot

logger = logging.getLogger(__name__)

_lock = threading.Lock()

option_chain_state: Dict = {
    "connected":  False,
    "spot":       0.0,
    "timestamp":  None,          # UTC ISO time of the last NIFTY spot tick
    "expiry":     None,          # the ONE expiry being tracked (ISO string)
    "atm":        0,
    "strikes":    {},            # {strike: {"ce": {...}, "pe": {...}}}
    "prev_oi":    {},            # {token: previous trading day's closing OI}
    "guidance":   None,          # latest engine result (set by the router)
}

_strike_map: Dict = {}
_active_expiry: Optional[str] = None

NIFTY_INDEX_TOKEN = "26000"
NFO_EXCHANGE_TYPE = 2
NSE_EXCHANGE_TYPE = 1
MODE_LTP         = 1
MODE_SNAPQUOTE   = 3

MAX_SESSION_AGE = timedelta(hours=6)
SUBSCRIBE_BATCH_SIZE = 200
RECONNECT_PAUSE_SECONDS = 10


# ---------------------------------------------------------------------------
# Angel One auth
# ---------------------------------------------------------------------------

def _session_is_stale(session_row) -> bool:
    if not session_row or not session_row.jwt_token or not session_row.feed_token:
        return True
    if not session_row.logged_in_at:
        return True
    return (datetime.utcnow() - session_row.logged_in_at) > MAX_SESSION_AGE


def _get_credentials(db_factory, force_fresh: bool = False) -> tuple:
    from app.models import AngelSession
    from app import angel_client

    with db_factory() as db:
        session_row = db.query(AngelSession).first()
        if force_fresh or _session_is_stale(session_row):
            logger.info("Angel One session is stale/missing or last attempt failed - fresh login.")
            session_row = angel_client._login_and_store(
                db, settings.angel_client_code, settings.angel_mpin,
                settings.angel_api_key, settings.angel_totp_secret,
            )
        jwt = session_row.jwt_token
        feed_token = session_row.feed_token

    if not jwt or not feed_token:
        raise RuntimeError("Angel One login did not return a jwt_token / feed_token.")
    return jwt, feed_token, settings.angel_api_key, settings.angel_client_code


# ---------------------------------------------------------------------------
# Tick processing
# ---------------------------------------------------------------------------

def _ltp_from_paise(paise: int) -> float:
    return round(paise / 100, 2)


def _process_tick(message: dict) -> None:
    token      = str(message.get("token", ""))
    raw_ltp    = message.get("last_traded_price", 0)
    raw_oi     = message.get("open_interest", 0)
    raw_volume = message.get("volume_trade_for_the_day", 0)
    ltp        = _ltp_from_paise(raw_ltp)

    if token == NIFTY_INDEX_TOKEN:
        with _lock:
            option_chain_state["spot"] = ltp
            option_chain_state["timestamp"] = datetime.utcnow().isoformat()
        return

    info = _strike_map.get(token)
    if not info:
        return
    # Only the nearest expiry is tracked; ignore anything else completely.
    if _active_expiry is not None and info["expiry"] != _active_expiry:
        return

    strike   = info["strike"]
    opt_type = info["option_type"].lower()
    prev_oi  = option_chain_state["prev_oi"].get(token, 0)
    oi_chg_pct = ((raw_oi - prev_oi) / prev_oi * 100) if prev_oi > 0 else 0.0
    voi = round(raw_volume / raw_oi, 3) if raw_oi > 0 else 0.0

    with _lock:
        if strike not in option_chain_state["strikes"]:
            option_chain_state["strikes"][strike] = {"ce": None, "pe": None}
        option_chain_state["strikes"][strike][opt_type] = {
            "ltp": ltp, "oi": raw_oi, "oi_chg_pct": round(oi_chg_pct, 2),
            "volume": raw_volume, "voi": voi, "expiry": info["expiry"], "token": token,
        }


# ---------------------------------------------------------------------------
# WebSocket thread
# ---------------------------------------------------------------------------

_ws_thread:    Optional[threading.Thread] = None
_stop_event    = threading.Event()
_sws_instance: Optional[SmartWebSocketV2] = None


def _ws_worker(tokens: List[str], db_factory) -> None:
    global _sws_instance
    force_fresh = False

    while not _stop_event.is_set():
        opened = {"value": False}
        try:
            auth_token, feed_token, api_key, client_code = _get_credentials(
                db_factory, force_fresh=force_fresh)

            sws = SmartWebSocketV2(auth_token, api_key, client_code, feed_token)
            _sws_instance = sws

            def on_open(ws, *_args):
                logger.info("Angel One option WS opened")
                opened["value"] = True
                with _lock:
                    option_chain_state["connected"] = True
                for n, i in enumerate(range(0, len(tokens), SUBSCRIBE_BATCH_SIZE)):
                    batch = tokens[i:i + SUBSCRIBE_BATCH_SIZE]
                    sws.subscribe(f"optchn{n:03d}", MODE_SNAPQUOTE,
                                  [{"exchangeType": NFO_EXCHANGE_TYPE, "tokens": batch}])
                    time.sleep(0.2)
                sws.subscribe("niftyspot", MODE_LTP,
                              [{"exchangeType": NSE_EXCHANGE_TYPE, "tokens": [NIFTY_INDEX_TOKEN]}])
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

            sws.on_open, sws.on_data = on_open, on_data
            sws.on_error, sws.on_close = on_error, on_close
            sws.connect()   # blocking

            with _lock:
                option_chain_state["connected"] = False
            if opened["value"]:
                force_fresh = False
            else:
                logger.warning("Option WS never opened - will log in fresh on next attempt.")
                force_fresh = True

        except Exception as exc:
            logger.error(f"WS worker error: {exc}. Retrying in {RECONNECT_PAUSE_SECONDS}s...")
            with _lock:
                option_chain_state["connected"] = False
            force_fresh = True

        _stop_event.wait(RECONNECT_PAUSE_SECONDS)

    logger.info("WS worker stopped.")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _pick_active_expiry(strike_map: dict) -> Optional[str]:
    today_iso = now_ist_naive().date().isoformat()
    expiries = sorted({v["expiry"] for v in strike_map.values()})
    future = [e for e in expiries if e >= today_iso]
    if future:
        return future[0]
    return expiries[-1] if expiries else None


def load_strike_map(strike_map: dict) -> None:
    """Stores the token map and decides which single expiry is tracked."""
    global _strike_map, _active_expiry
    _strike_map = strike_map
    _active_expiry = _pick_active_expiry(strike_map)
    with _lock:
        option_chain_state["expiry"] = _active_expiry
    logger.info(f"Tracking nearest expiry only: {_active_expiry}")


def get_active_expiry() -> Optional[date]:
    return date.fromisoformat(_active_expiry) if _active_expiry else None


def reset_state() -> None:
    """Wipes live data (used when a new trading day starts)."""
    with _lock:
        option_chain_state.update({
            "spot": 0.0, "timestamp": None, "strikes": {}, "prev_oi": {}, "guidance": None,
        })


def load_prev_oi(db: Session) -> None:
    """
    Loads the previous trading day's closing OI per token (for the 'OI vs
    yesterday' figure). Reads the last 1-minute snapshot of the most recent
    earlier day; falls back to the EOD snapshot table.
    """
    if not _active_expiry:
        return
    active_date = date.fromisoformat(_active_expiry)
    today_start = datetime.combine(now_ist_naive().date(), datetime.min.time())

    reverse = {
        (v["strike"], v["option_type"]): tok
        for tok, v in _strike_map.items() if v["expiry"] == _active_expiry
    }
    prev: Dict[str, int] = {}

    last_ts = (
        db.query(func.max(OptionMinuteSnapshot.bucket_ts))
        .filter(OptionMinuteSnapshot.bucket_ts < today_start,
                OptionMinuteSnapshot.expiry == active_date)
        .scalar()
    )
    if last_ts:
        rows = (
            db.query(OptionMinuteSnapshot)
            .filter(OptionMinuteSnapshot.bucket_ts == last_ts,
                    OptionMinuteSnapshot.expiry == active_date)
            .all()
        )
        for r in rows:
            ce_tok, pe_tok = reverse.get((r.strike, "CE")), reverse.get((r.strike, "PE"))
            if ce_tok and r.ce_oi:
                prev[ce_tok] = r.ce_oi
            if pe_tok and r.pe_oi:
                prev[pe_tok] = r.pe_oi
        source = f"minute snapshot {last_ts}"
    else:
        last_day = (
            db.query(func.max(OptionEodSnapshot.date))
            .filter(OptionEodSnapshot.date < today_start.date(),
                    OptionEodSnapshot.expiry == active_date)
            .scalar()
        )
        source = "none"
        if last_day:
            rows = (
                db.query(OptionEodSnapshot)
                .filter(OptionEodSnapshot.date == last_day, OptionEodSnapshot.expiry == active_date)
                .all()
            )
            for r in rows:
                ce_tok, pe_tok = reverse.get((r.strike, "CE")), reverse.get((r.strike, "PE"))
                if ce_tok and r.ce_oi:
                    prev[ce_tok] = r.ce_oi
                if pe_tok and r.pe_oi:
                    prev[pe_tok] = r.pe_oi
            source = f"EOD snapshot {last_day}"

    with _lock:
        option_chain_state["prev_oi"] = prev
    logger.info(f"Loaded prev-OI for {len(prev)} tokens from {source}")


def start_stream(tokens: List[str], strike_map: dict, db_factory) -> None:
    global _ws_thread
    if _ws_thread and _ws_thread.is_alive():
        logger.info("Option stream already running.")
        return

    load_strike_map(strike_map)
    active_tokens = [t for t in tokens if _strike_map.get(t, {}).get("expiry") == _active_expiry]
    if not active_tokens:
        active_tokens = list(tokens)

    _stop_event.clear()
    _ws_thread = threading.Thread(
        target=_ws_worker, args=(active_tokens, db_factory), daemon=True, name="option-ws")
    _ws_thread.start()
    logger.info(f"Option stream thread started ({len(active_tokens)} tokens).")


def stop_stream(wait: bool = False) -> None:
    _stop_event.set()
    if _sws_instance:
        try:
            _sws_instance.close_connection()
        except Exception:
            pass
    if wait and _ws_thread and _ws_thread.is_alive():
        _ws_thread.join(timeout=20)
    logger.info("Option stream stop requested.")


def get_snapshot() -> dict:
    with _lock:
        import copy
        return copy.deepcopy(option_chain_state)


def update_guidance(result: dict) -> None:
    with _lock:
        option_chain_state["guidance"] = result
