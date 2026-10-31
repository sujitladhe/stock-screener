"""
EOD snapshot + daily summary jobs.

These now run INSIDE the web server (the router triggers them a couple of
minutes after the 15:30 close), because the live option data only exists in
the server's memory. The old cron script (scripts/save_option_eod.py) runs in
a separate process with empty memory; both functions below now refuse to save
anything when there is no live data, so it can no longer overwrite good rows
with zeros. You can safely remove that cron line.
"""

import logging
from datetime import datetime, date
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import now_ist_naive
from app.options.models import OptionEodSnapshot, OptionDailySummary, OptionGuidanceLog
from app.options.option_stream import get_snapshot
from app.options.guidance import engine

logger = logging.getLogger(__name__)


def save_eod_snapshot(db: Session) -> dict:
    state = get_snapshot()
    today = now_ist_naive().date()
    strikes_data = state.get("strikes", {})

    if not strikes_data:
        logger.warning("EOD snapshot called but no strike data in memory.")
        return {"saved": 0, "date": today.isoformat()}

    expiry_iso = state.get("expiry")
    try:
        expiry_date = date.fromisoformat(expiry_iso) if expiry_iso else today
    except Exception:
        expiry_date = today

    saved = 0
    for strike, side in strikes_data.items():
        ce = side.get("ce") or {}
        pe = side.get("pe") or {}
        values = dict(
            ce_oi=ce.get("oi"), pe_oi=pe.get("oi"),
            ce_ltp=ce.get("ltp"), pe_ltp=pe.get("ltp"),
            ce_volume=ce.get("volume"), pe_volume=pe.get("volume"),
            created_at=datetime.utcnow(),
        )
        stmt = (
            pg_insert(OptionEodSnapshot)
            .values(date=today, expiry=expiry_date, strike=strike, **values)
            .on_conflict_do_update(constraint="uq_option_eod_date_expiry_strike", set_=values)
        )
        db.execute(stmt)
        saved += 1

    try:
        db.commit()
        logger.info(f"EOD snapshot saved: {saved} strikes for {today}")
    except Exception as exc:
        db.rollback()
        logger.error(f"EOD snapshot commit failed: {exc}")
        raise
    return {"saved": saved, "date": today.isoformat()}


def save_daily_summary(db: Session) -> dict:
    state = get_snapshot()
    today = now_ist_naive().date()
    spot = state.get("spot", 0.0)
    m = engine.last_metrics

    if spot <= 0 or not state.get("strikes") or not m:
        logger.warning("Daily summary skipped: no live data / no engine decision in this process.")
        return {"saved": False, "reason": "no live data in this process", "date": today.isoformat()}

    expiry_iso = state.get("expiry")
    try:
        expiry_date = date.fromisoformat(expiry_iso) if expiry_iso else today
    except Exception:
        expiry_date = today

    values = dict(
        expiry=expiry_date, spot_close=round(spot, 2), pcr=m.get("pcr"),
        max_pain=m.get("max_pain"), atm_iv=m.get("atm_iv"), iv_skew=m.get("iv_skew"),
        expected_move_range=m.get("expected_move"), created_at=datetime.utcnow(),
    )
    stmt = (
        pg_insert(OptionDailySummary)
        .values(date=today, **values)
        .on_conflict_do_update(constraint="uq_option_daily_summary_date", set_=values)
    )
    try:
        db.execute(stmt)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error(f"Daily summary commit failed: {exc}")
        raise
    return {"saved": True, "date": today.isoformat(), "pcr": m.get("pcr"),
            "max_pain": m.get("max_pain"), "atm_iv": m.get("atm_iv"), "iv_skew": m.get("iv_skew")}


def log_guidance(db: Session, result: dict) -> None:
    """Legacy hourly log (kept for compatibility; the decision log replaces it)."""
    opps = result.get("opportunities") or []
    opp = opps[0] if opps else {}
    state = get_snapshot()
    row = OptionGuidanceLog(
        logged_at=datetime.utcnow(),
        expiry=_parse_expiry(state.get("expiry")),
        spot=state.get("spot"), score=result.get("score"), bias=result.get("bias"),
        confidence=result.get("confidence"),
        top_opportunity_strike=opp.get("strike"), top_opportunity_type=opp.get("type"),
        signal_breakdown={"signals": result.get("signals", []),
                          "pcr": result.get("pcr"), "iv_skew": result.get("iv_skew")},
        created_at=datetime.utcnow(),
    )
    try:
        db.add(row)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error(f"Guidance log commit failed: {exc}")


def _parse_expiry(iso):
    if not iso:
        return None
    try:
        return date.fromisoformat(iso)
    except Exception:
        return None
