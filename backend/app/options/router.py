"""
Options FastAPI router.

Routes (all under /options):
  POST /stream/start | /stream/stop      start / stop the Angel One stream
  GET  /chain                            current live snapshot
  GET  /status                           stream health
  GET  /engine/status                    engine memory + bias state
  GET  /history?date=                    EOD OI snapshot for a past date
  GET  /decisions?day=                   every engine decision of a day (+ outcomes)
  GET  /decisions/stats?days=30          how often the engine was right
  POST /eod/snapshot                     manual EOD save
  POST /master/refresh                   refresh instrument master
  WS   /ws                               live broadcast to the dashboard

Background tasks (started by startup()):
  * broadcast loop  - every 1.5 s pushes the live chain + latest guidance to browsers
  * recorder loop   - every minute (market hours): stores a 1-minute snapshot
                      (memory + DB), scans for fake spikes; every 5th minute runs the
                      full guidance decision, saves it to the decision log and fills in
                      outcomes of earlier decisions. Also does the daily 09:05 rollover
                      and the after-close EOD save / old-data cleanup.
"""

import asyncio
import json
import logging
from datetime import date, datetime, time as dtime
from typing import Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import now_ist_naive
from app.options.instrument_master import (
    fetch_and_store_instrument_master,
    get_tokens_for_subscription,
    get_strike_map,
)
from app.options import option_stream as stream
from app.options import history as history_mod
from app.options import decision_log
from app.options.history import history, STORE_RANGE_PTS
from app.options.guidance import engine, EVAL_EVERY_MIN
from app.options.eod_job import save_eod_snapshot, save_daily_summary
from app.options.models import OptionEodSnapshot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/options", tags=["options"])

BROADCAST_INTERVAL_S = 1.5
MAX_DATA_AGE_S = 90          # a snapshot older than this is not recorded (feed is stale)

_ws_clients: Set[WebSocket] = set()
_tasks: list = []
_state = {"eod_done": None, "rollover_done": None}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_market_open(now: datetime) -> bool:
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 30)


def _snapshot_is_fresh(snap: dict) -> bool:
    ts = snap.get("timestamp")
    if not ts or not snap.get("connected"):
        return False
    try:
        age = (datetime.utcnow() - datetime.fromisoformat(ts)).total_seconds()
    except Exception:
        return False
    return age <= MAX_DATA_AGE_S


def _ensure_current_master(db: Session):
    """Returns (tokens, strike_map); fetches a fresh master if none / all expired."""
    tokens = get_tokens_for_subscription(db)
    smap = get_strike_map(db)
    today_iso = now_ist_naive().date().isoformat()
    if not tokens or not any(v["expiry"] >= today_iso for v in smap.values()):
        logger.info("Instrument master missing or expired - fetching fresh...")
        result = fetch_and_store_instrument_master(db)
        tokens = result["tokens"]
        smap = get_strike_map(db)
    return tokens, smap


def _payload_strikes(snap: dict) -> dict:
    spot = snap.get("spot") or 0
    out = {}
    for k, v in snap["strikes"].items():
        if spot and abs(k - spot) > STORE_RANGE_PTS:
            continue
        out[str(k)] = v
    return out


def _build_payload() -> str:
    snap = stream.get_snapshot()
    spot = snap["spot"]
    return json.dumps({
        "connected": snap["connected"],
        "spot":      spot,
        "timestamp": snap["timestamp"],
        "expiry":    snap["expiry"],
        "atm":       int(round(spot / 50) * 50) if spot else 0,
        "strikes":   _payload_strikes(snap),
        "guidance":  snap.get("guidance"),
    })


# ---------------------------------------------------------------------------
# Background loops
# ---------------------------------------------------------------------------

async def _broadcast_loop() -> None:
    global _ws_clients
    while True:
        await asyncio.sleep(BROADCAST_INTERVAL_S)
        if not _ws_clients:
            continue
        payload = _build_payload()
        dead: Set[WebSocket] = set()
        for ws in list(_ws_clients):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        _ws_clients -= dead


def _persist_bucket(db_factory, bucket) -> None:
    with db_factory() as db:
        history_mod.persist_bucket(db, bucket)


def _after_decision(db_factory, result, now) -> None:
    with db_factory() as db:
        if not result.get("warming_up"):
            decision_log.save_decision(db, result)
        decision_log.fill_outcomes(db, now)


def _eod_work(db_factory, now) -> None:
    with db_factory() as db:
        try:
            logger.info(f"EOD snapshot: {save_eod_snapshot(db)}")
        except Exception as e:
            logger.error(f"EOD snapshot failed: {e}")
    with db_factory() as db:
        try:
            logger.info(f"Daily summary: {save_daily_summary(db)}")
        except Exception as e:
            logger.error(f"Daily summary failed: {e}")
    with db_factory() as db:
        try:
            logger.info(f"Purged {history_mod.purge_old(db, now)} old 1-minute rows.")
        except Exception as e:
            logger.error(f"Purge failed: {e}")


def _rollover_work(db_factory):
    """Daily 09:05: reload the instrument master (nearest expiry) and restart the stream."""
    stream.stop_stream(wait=True)
    stream.reset_state()
    with db_factory() as db:
        tokens, smap = _ensure_current_master(db)
        stream.load_strike_map(smap)
        stream.load_prev_oi(db)
    stream.start_stream(tokens, smap, db_factory)


async def _recorder_tick(db_factory) -> None:
    now = now_ist_naive()
    today, t = now.date(), now.time()

    # 1) daily rollover (weekdays 09:05 - 09:13)
    if now.weekday() < 5 and dtime(9, 5) <= t < dtime(9, 14) and _state["rollover_done"] != today:
        _state["rollover_done"] = today
        logger.info("Daily rollover: refreshing instrument master and restarting stream.")
        await asyncio.to_thread(_rollover_work, db_factory)
        history.clear()
        engine.reset_for_new_day()
        stream.update_guidance(engine.result)
        return

    # 2) market hours: record a 1-minute snapshot, scan spikes, decide every 5th minute
    if _is_market_open(now):
        snap = stream.get_snapshot()
        if _snapshot_is_fresh(snap):
            ts = now.replace(second=0, microsecond=0)
            bucket = history_mod.build_bucket(snap, ts)
            if bucket:
                history.add(bucket)
                try:
                    await asyncio.to_thread(_persist_bucket, db_factory, bucket)
                except Exception as e:
                    logger.error(f"Could not save 1-minute snapshot: {e}")

                if now.minute % EVAL_EVERY_MIN == 0:
                    result = engine.evaluate()
                    stream.update_guidance(result)
                    try:
                        await asyncio.to_thread(_after_decision, db_factory, result, now)
                    except Exception as e:
                        logger.error(f"Could not save decision: {e}")
                    logger.info(
                        f"Decision {ts:%H:%M}: bias={result['bias']} (raw {result['raw_bias']}, "
                        f"score {result['score']:+d}) pending={result['pending_bias']} "
                        f"opps={len(result['opportunities'])} spikes={len(result['spike_alerts'])}"
                        if not result.get("warming_up") else
                        f"Decision {ts:%H:%M}: warming up - {result.get('message')}")
                else:
                    result = engine.update_spikes()
                    if result is not None:
                        stream.update_guidance(result)
        return

    # 3) after the close (weekdays, from 15:32): save EOD data once, purge old rows
    if now.weekday() < 5 and t >= dtime(15, 32) and _state["eod_done"] != today:
        _state["eod_done"] = today
        await asyncio.to_thread(_eod_work, db_factory, now)


async def _recorder_loop(db_factory) -> None:
    while True:
        now = datetime.now()
        # wake up at second :01 of the next minute
        await asyncio.sleep(61.0 - (now.second + now.microsecond / 1e6))
        try:
            await _recorder_tick(db_factory)
        except Exception:
            logger.exception("Recorder tick failed")


# ---------------------------------------------------------------------------
# Startup / shutdown (called from main.py)
# ---------------------------------------------------------------------------

async def startup(db_factory) -> None:
    try:
        def _prepare():
            with db_factory() as db:
                tokens, smap = _ensure_current_master(db)
                stream.load_strike_map(smap)
                stream.load_prev_oi(db)
                expiry = stream.get_active_expiry()
                loaded = 0
                today = now_ist_naive().date()
                if expiry:
                    loaded = history.load_today(db, expiry, today)
                decision_log.restore_state(db, engine, today)
            return tokens, smap, loaded

        tokens, smap, loaded = await asyncio.to_thread(_prepare)
        logger.info(f"Engine memory: reloaded {loaded} one-minute snapshots from today.")
        stream.start_stream(tokens, smap, db_factory)
    except Exception as exc:
        logger.error(f"Options startup error: {exc}")

    stream.update_guidance(engine.result)
    _tasks.append(asyncio.create_task(_broadcast_loop()))
    _tasks.append(asyncio.create_task(_recorder_loop(db_factory)))
    logger.info("Options broadcast + recorder loops started.")


async def shutdown() -> None:
    for t in _tasks:
        t.cancel()
    stream.stop_stream()


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@router.post("/stream/start")
def start_stream(db: Session = Depends(get_db)):
    tokens, smap = _ensure_current_master(db)
    stream.load_strike_map(smap)
    stream.load_prev_oi(db)
    from app.database import SessionLocal
    stream.start_stream(tokens, smap, SessionLocal)
    return {"status": "started", "tokens": len(tokens)}


@router.post("/stream/stop")
def stop_stream():
    stream.stop_stream()
    return {"status": "stopped"}


@router.get("/status")
def get_status():
    snap = stream.get_snapshot()
    return {"connected": snap["connected"], "spot": snap["spot"],
            "strikes": len(snap["strikes"]), "timestamp": snap["timestamp"],
            "expiry": snap["expiry"]}


@router.get("/engine/status")
def engine_status():
    latest = history.latest()
    return {
        "bias": engine.bias,
        "bias_since": engine.bias_since.isoformat() if engine.bias_since else None,
        "pending_bias": engine.pending, "pending_count": engine.pending_count,
        "snapshots_in_memory": len(history.buckets),
        "minutes_of_data": history.minutes_of_data(),
        "latest_snapshot": latest["ts"].isoformat() if latest else None,
        "last_evaluated_at": engine.result.get("evaluated_at"),
        "warming_up": engine.result.get("warming_up"),
    }


@router.get("/chain")
def get_chain():
    snap = stream.get_snapshot()
    spot = snap["spot"]
    return {
        "connected": snap["connected"], "spot": spot, "expiry": snap["expiry"],
        "atm": int(round(spot / 50) * 50) if spot else 0,
        "strikes": _payload_strikes(snap), "guidance": snap.get("guidance"),
    }


@router.get("/history")
def get_history(
    query_date: Optional[str] = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
):
    if query_date:
        try:
            target = date.fromisoformat(query_date)
        except ValueError:
            raise HTTPException(400, "date must be YYYY-MM-DD")
    else:
        target = now_ist_naive().date()
    rows = (
        db.query(OptionEodSnapshot)
        .filter(OptionEodSnapshot.date == target)
        .order_by(OptionEodSnapshot.strike)
        .all()
    )
    return [
        {"strike": r.strike, "expiry": r.expiry.isoformat(), "ce_oi": r.ce_oi, "pe_oi": r.pe_oi,
         "ce_ltp": float(r.ce_ltp) if r.ce_ltp else None,
         "pe_ltp": float(r.pe_ltp) if r.pe_ltp else None,
         "ce_volume": r.ce_volume, "pe_volume": r.pe_volume}
        for r in rows
    ]


@router.get("/decisions")
def get_decisions(day: Optional[str] = None, db: Session = Depends(get_db)):
    try:
        d = date.fromisoformat(day) if day else now_ist_naive().date()
    except ValueError:
        raise HTTPException(400, "day must be YYYY-MM-DD")
    return decision_log.get_decisions(db, d)


@router.get("/decisions/stats")
def get_decision_stats(days: int = Query(default=30, ge=1, le=365), db: Session = Depends(get_db)):
    return decision_log.get_stats(db, days, now_ist_naive())


@router.post("/eod/snapshot")
def trigger_eod_snapshot(db: Session = Depends(get_db)):
    return {"snapshot": save_eod_snapshot(db), "summary": save_daily_summary(db)}


@router.post("/master/refresh")
def refresh_master(spot: Optional[float] = None, db: Session = Depends(get_db)):
    return fetch_and_store_instrument_master(db, spot_price=spot)


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/ws")
async def option_ws(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.add(websocket)
    try:
        await websocket.send_text(_build_payload())
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"Option WS error: {e}")
    finally:
        _ws_clients.discard(websocket)
