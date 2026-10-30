"""
EOD snapshot + daily summary jobs.
Run by cron at 15:30 IST (10:00 UTC) via scripts/save_option_eod.py.
Also callable from an API endpoint for manual triggers.
"""

import logging
from datetime import datetime, date
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.options.models import OptionEodSnapshot, OptionDailySummary, OptionGuidanceLog
from app.options.option_stream import get_snapshot
from app.options.guidance import run_engine

logger = logging.getLogger(__name__)


def save_eod_snapshot(db: Session) -> dict:
    """
    Snapshot the current in-memory option chain state and persist to
    option_eod_snapshot. Upserts — safe to call more than once on the
    same day (last write wins).
    """
    state  = get_snapshot()
    today  = date.today()
    strikes_data = state.get("strikes", {})

    if not strikes_data:
        logger.warning("EOD snapshot called but no strike data in memory.")
        return {"saved": 0, "date": today.isoformat()}

    # Determine active expiry
    expiry_iso = state.get("expiry")
    if expiry_iso:
        try:
            expiry_date = date.fromisoformat(expiry_iso)
        except Exception:
            expiry_date = today
    else:
        expiry_date = today

    saved = 0
    for strike, side in strikes_data.items():
        ce = side.get("ce") or {}
        pe = side.get("pe") or {}

        # Use the expiry from the CE side if available (more reliable)
        row_expiry = expiry_date
        if ce.get("expiry"):
            try:
                row_expiry = date.fromisoformat(ce["expiry"])
            except Exception:
                pass

        stmt = (
            pg_insert(OptionEodSnapshot)
            .values(
                date       = today,
                expiry     = row_expiry,
                strike     = strike,
                ce_oi      = ce.get("oi"),
                pe_oi      = pe.get("oi"),
                ce_ltp     = ce.get("ltp"),
                pe_ltp     = pe.get("ltp"),
                ce_volume  = ce.get("volume"),
                pe_volume  = pe.get("volume"),
                created_at = datetime.utcnow(),
            )
            .on_conflict_do_update(
                constraint="uq_option_eod_date_expiry_strike",
                set_={
                    "ce_oi":    ce.get("oi"),
                    "pe_oi":    pe.get("oi"),
                    "ce_ltp":   ce.get("ltp"),
                    "pe_ltp":   pe.get("ltp"),
                    "ce_volume": ce.get("volume"),
                    "pe_volume": pe.get("volume"),
                    "created_at": datetime.utcnow(),
                },
            )
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
    """
    Compute and persist the daily summary (PCR, max pain, IV skew, etc.)
    by running the guidance engine once more on the final state.
    """
    state   = get_snapshot()
    today   = date.today()
    spot    = state.get("spot", 0.0)

    engine_result = run_engine(state)
    pcr      = engine_result.get("pcr")
    max_pain = engine_result.get("max_pain")
    iv_skew  = engine_result.get("iv_skew")

    # Compute ATM IV (CE + PE average at ATM)
    atm_iv = _compute_atm_iv(state, spot)

    expiry_iso = state.get("expiry")
    try:
        expiry_date = date.fromisoformat(expiry_iso) if expiry_iso else today
    except Exception:
        expiry_date = today

    stmt = (
        pg_insert(OptionDailySummary)
        .values(
            date                = today,
            expiry              = expiry_date,
            spot_close          = round(spot, 2),
            pcr                 = pcr,
            max_pain            = max_pain,
            atm_iv              = atm_iv,
            iv_skew             = iv_skew,
            expected_move_range = _compute_expected_move(spot, atm_iv),
            created_at          = datetime.utcnow(),
        )
        .on_conflict_do_update(
            constraint="uq_option_daily_summary_date",
            set_={
                "spot_close":          round(spot, 2),
                "pcr":                 pcr,
                "max_pain":            max_pain,
                "atm_iv":              atm_iv,
                "iv_skew":             iv_skew,
                "expected_move_range": _compute_expected_move(spot, atm_iv),
                "created_at":          datetime.utcnow(),
            },
        )
    )

    try:
        db.execute(stmt)
        db.commit()
        logger.info(f"Daily summary saved for {today}: PCR={pcr}, max_pain={max_pain}")
    except Exception as exc:
        db.rollback()
        logger.error(f"Daily summary commit failed: {exc}")
        raise

    return {
        "date":     today.isoformat(),
        "pcr":      pcr,
        "max_pain": max_pain,
        "atm_iv":   atm_iv,
        "iv_skew":  iv_skew,
    }


def log_guidance(db: Session, result: dict) -> None:
    """
    Persist a guidance engine snapshot (called hourly from the broadcast loop).
    Not upserted — every call creates a new row for the time-series log.
    """
    opp = result.get("opportunities", [{}])[0] if result.get("opportunities") else {}
    state = get_snapshot()

    row = OptionGuidanceLog(
        logged_at              = datetime.utcnow(),
        expiry                 = _parse_expiry(state.get("expiry")),
        spot                   = state.get("spot"),
        score                  = result.get("score"),
        bias                   = result.get("bias"),
        confidence             = result.get("confidence"),
        top_opportunity_strike = opp.get("strike"),
        top_opportunity_type   = opp.get("type"),
        signal_breakdown       = {
            "signals": result.get("signals", []),
            "pcr":     result.get("pcr"),
            "iv_skew": result.get("iv_skew"),
        },
        created_at = datetime.utcnow(),
    )
    try:
        db.add(row)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error(f"Guidance log commit failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_expiry(iso: str | None):
    if not iso:
        return None
    try:
        return date.fromisoformat(iso)
    except Exception:
        return None


def _compute_atm_iv(state: dict, spot: float) -> float:
    """Average of ATM CE and PE IV approximation."""
    import math
    atm = round(spot / 50) * 50
    strikes = state.get("strikes", {})
    ce_ltp = (strikes.get(atm, {}).get("ce") or {}).get("ltp", 0)
    pe_ltp = (strikes.get(atm, {}).get("pe") or {}).get("ltp", 0)
    t_days = 7.0  # rough default
    T = t_days / 365.0

    ivs = []
    for ltp in [ce_ltp, pe_ltp]:
        if ltp and spot > 0 and T > 0:
            try:
                iv = (ltp / spot) * math.sqrt(2 * math.pi / T) * 100
                ivs.append(iv)
            except Exception:
                pass
    return round(sum(ivs) / len(ivs), 2) if ivs else 0.0


def _compute_expected_move(spot: float, atm_iv_pct: float) -> float:
    """
    Expected daily move ≈ spot × IV × sqrt(1/252).
    Returns in points (₹).
    """
    import math
    if spot <= 0 or atm_iv_pct <= 0:
        return 0.0
    return round(spot * (atm_iv_pct / 100) * math.sqrt(1 / 252), 1)
