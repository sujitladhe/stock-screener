"""
Options FastAPI router.

Routes:
  POST /options/stream/start    — start Angel One WS stream
  POST /options/stream/stop     — stop it
  GET  /options/chain           — current snapshot (for initial page load)
  GET  /options/status          — stream health check
  GET  /options/history?date=   — EOD snapshot for a past date
  POST /options/eod/snapshot    — manual trigger EOD save
  WS   /options/ws              — real-time broadcast WebSocket

Lifespan:
  On app startup: instrument master loaded, stream started.
  Background asyncio task broadcasts every 1.5 s to all WS clients.
  Guidance engine runs every 12 s inside the broadcast loop.
"""

import asyncio
import json
import logging
from datetime import date
from typing import Optional, Set

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.database import get_db
from app.options.instrument_master import (
    fetch_and_store_instrument_master,
    get_tokens_for_subscription,
    get_strike_map,
)
from app.options import option_stream as stream
from app.options.guidance import run_engine
from app.options.eod_job import save_eod_snapshot, save_daily_summary, log_guidance
from app.options.models import OptionEodSnapshot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/options", tags=["options"])

# ---------------------------------------------------------------------------
# WebSocket client registry
# ---------------------------------------------------------------------------
_ws_clients: Set[WebSocket] = set()

# ---------------------------------------------------------------------------
# Background broadcast + guidance task
# ---------------------------------------------------------------------------
_guidance_tick = 0   # incremented each broadcast; guidance runs every 8th (12 s)
BROADCAST_INTERVAL_S  = 1.5
GUIDANCE_EVERY_N      = 8     # 8 × 1.5 s = 12 s
GUIDANCE_LOG_EVERY_N  = 2400  # log every hour (~2400 × 1.5 s)


async def _broadcast_loop(db_factory) -> None:
    global _guidance_tick, _ws_clients   # _ws_clients needed because -= rebinds it
    while True:
        await asyncio.sleep(BROADCAST_INTERVAL_S)

        if not _ws_clients:
            _guidance_tick += 1
            continue

        # Run guidance engine periodically
        _guidance_tick += 1
        if _guidance_tick % GUIDANCE_EVERY_N == 0:
            state  = stream.get_snapshot()
            result = run_engine(state)
            stream.update_guidance(result)

            # Hourly guidance log
            if _guidance_tick % GUIDANCE_LOG_EVERY_N == 0:
                try:
                    with db_factory() as db:
                        log_guidance(db, result)
                except Exception as e:
                    logger.error(f"Guidance log failed: {e}")

        payload = _build_payload()
        dead: Set[WebSocket] = set()
        for ws in list(_ws_clients):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        _ws_clients -= dead


def _build_payload() -> str:
    """Serialise current option chain state for the frontend."""
    snap = stream.get_snapshot()
    return json.dumps({
        "connected":    snap["connected"],
        "spot":         snap["spot"],
        "timestamp":    snap["timestamp"],
        "expiry":       snap["expiry"],
        "atm":          snap["atm"],
        "strikes":      {
            str(k): v for k, v in snap["strikes"].items()
        },
        "guidance":     snap.get("guidance"),
    })


# ---------------------------------------------------------------------------
# Startup / shutdown helpers (called from main.py lifespan)
# ---------------------------------------------------------------------------

async def startup(db_factory) -> None:
    """
    1. Load instrument master (or fetch fresh if table is empty).
    2. Load yesterday's OI from DB into memory.
    3. Start Angel One WebSocket thread.
    4. Launch background broadcast task.
    """
    try:
        with db_factory() as db:
            tokens = get_tokens_for_subscription(db)
            if not tokens:
                logger.info("Instrument master empty — fetching fresh…")
                result = fetch_and_store_instrument_master(db)
                tokens = result["tokens"]
            strike_map = get_strike_map(db)

            # Load prev-OI while the session is still open
            stream.load_strike_map(strike_map)
            stream.load_prev_oi(db)

        # Pass db_factory (not a closed db instance) so the thread can open
        # fresh sessions when it needs to re-read credentials on reconnect.
        stream.start_stream(tokens, strike_map, db_factory)

    except Exception as exc:
        logger.error(f"Options startup error: {exc}")
        # Non-fatal — stream can be started manually via POST /options/stream/start

    asyncio.create_task(_broadcast_loop(db_factory))
    logger.info("Options broadcast loop started.")


async def shutdown() -> None:
    stream.stop_stream()


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@router.post("/stream/start")
def start_stream(db: Session = Depends(get_db)):
    tokens = get_tokens_for_subscription(db)
    if not tokens:
        result = fetch_and_store_instrument_master(db)
        tokens = result["tokens"]
    strike_map = get_strike_map(db)
    stream.load_strike_map(strike_map)
    stream.load_prev_oi(db)
    from app.database import SessionLocal
    stream.start_stream(tokens, strike_map, SessionLocal)
    return {"status": "started", "tokens": len(tokens)}


@router.post("/stream/stop")
def stop_stream():
    stream.stop_stream()
    return {"status": "stopped"}


@router.get("/status")
def get_status():
    snap = stream.get_snapshot()
    return {
        "connected": snap["connected"],
        "spot":      snap["spot"],
        "strikes":   len(snap["strikes"]),
        "timestamp": snap["timestamp"],
    }


@router.get("/chain")
def get_chain():
    """Full snapshot — used for initial page load before WS connects."""
    snap = stream.get_snapshot()
    return {
        "connected": snap["connected"],
        "spot":      snap["spot"],
        "expiry":    snap["expiry"],
        "atm":       snap["atm"],
        "strikes":   {str(k): v for k, v in snap["strikes"].items()},
        "guidance":  snap.get("guidance"),
    }


@router.get("/history")
def get_history(
    query_date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Returns EOD OI snapshot for a given date (YYYY-MM-DD).
    Defaults to today if no date supplied.
    """
    if query_date:
        try:
            target = date.fromisoformat(query_date)
        except ValueError:
            raise HTTPException(400, "date must be YYYY-MM-DD")
    else:
        target = date.today()

    rows = (
        db.query(OptionEodSnapshot)
        .filter(OptionEodSnapshot.date == target)
        .order_by(OptionEodSnapshot.strike)
        .all()
    )
    return [
        {
            "strike":    r.strike,
            "expiry":    r.expiry.isoformat(),
            "ce_oi":     r.ce_oi,
            "pe_oi":     r.pe_oi,
            "ce_ltp":    float(r.ce_ltp) if r.ce_ltp else None,
            "pe_ltp":    float(r.pe_ltp) if r.pe_ltp else None,
            "ce_volume": r.ce_volume,
            "pe_volume": r.pe_volume,
        }
        for r in rows
    ]


@router.post("/eod/snapshot")
def trigger_eod_snapshot(db: Session = Depends(get_db)):
    """Manual trigger for the EOD snapshot + daily summary."""
    snap_result    = save_eod_snapshot(db)
    summary_result = save_daily_summary(db)
    return {"snapshot": snap_result, "summary": summary_result}


@router.post("/master/refresh")
def refresh_master(
    spot: Optional[float] = None,
    db: Session = Depends(get_db),
):
    """Refresh instrument master from Angel One (call before market open)."""
    result = fetch_and_store_instrument_master(db, spot_price=spot)
    return result


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/ws")
async def option_ws(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.add(websocket)
    logger.debug(f"Option WS client connected. Total: {len(_ws_clients)}")
    try:
        # Send initial snapshot immediately
        await websocket.send_text(_build_payload())
        # Keep connection alive — frontend sends periodic pings
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"Option WS error: {e}")
    finally:
        _ws_clients.discard(websocket)
        logger.debug(f"Option WS client disconnected. Total: {len(_ws_clients)}")
