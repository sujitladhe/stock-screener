"""
decision_log.py — the engine's DIARY.

Every 5-minute decision is saved in option_decision_log together with the
NIFTY level at that moment. Later (15 / 30 / 60 minutes after) a background
step fills in what NIFTY actually did, so after a few weeks you can see which
rules really worked:  GET /options/decisions/stats
"""

import json
import logging
from datetime import datetime, date, time as dtime, timedelta
from typing import Dict, List

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.options.models import OptionDecisionLog, OptionMinuteSnapshot

logger = logging.getLogger(__name__)

NEUTRAL_HIT_PCT = 0.25     # NEUTRAL is "right" if NIFTY moved less than this % in 30 min


def _jsonable(obj):
    return json.loads(json.dumps(obj, default=str))


def save_decision(db: Session, result: dict) -> None:
    row = OptionDecisionLog(
        decided_at=datetime.fromisoformat(result["evaluated_at"]),
        expiry=date.fromisoformat(result["expiry"]) if result.get("expiry") else None,
        spot=result.get("spot"),
        raw_score=result.get("score"),
        raw_bias=result.get("raw_bias"),
        bias=result.get("bias"),
        pending_bias=result.get("pending_bias"),
        pending_count=result.get("pending_count"),
        confidence=result.get("confidence"),
        metrics=_jsonable({
            "pcr": result.get("pcr"), "max_pain": result.get("max_pain"),
            "iv_skew": result.get("iv_skew"), "atm_iv": result.get("atm_iv"),
            "expected_move": result.get("expected_move"),
            "oi_votes": result.get("oi_votes"), "window_min": result.get("window_min"),
        }),
        signals=_jsonable(result.get("signals")),
        opportunities=_jsonable(result.get("opportunities")),
        spike_alerts=_jsonable(result.get("spike_alerts")),
        created_at=datetime.utcnow(),
    )
    try:
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()
        raise


def restore_state(db: Session, engine, today: date) -> None:
    start = datetime.combine(today, dtime.min)
    row = (
        db.query(OptionDecisionLog)
        .filter(OptionDecisionLog.decided_at >= start)
        .order_by(OptionDecisionLog.decided_at.desc())
        .first()
    )
    if row:
        engine.restore(row.bias, row.pending_bias, row.pending_count, row.decided_at)
        logger.info(f"Restored engine bias {row.bias} from {row.decided_at}")


def fill_outcomes(db: Session, now: datetime) -> int:
    """Fills spot_15m/30m/60m and the 60-minute high/low for earlier decisions."""
    rows = (
        db.query(OptionDecisionLog)
        .filter(OptionDecisionLog.outcome_done == False,  # noqa: E712
                OptionDecisionLog.decided_at <= now - timedelta(minutes=15))
        .all()
    )
    updated = 0
    for r in rows:
        start = r.decided_at
        end = start + timedelta(minutes=60)
        pts = (
            db.query(OptionMinuteSnapshot.bucket_ts, func.max(OptionMinuteSnapshot.spot))
            .filter(OptionMinuteSnapshot.bucket_ts > start, OptionMinuteSnapshot.bucket_ts <= end)
            .group_by(OptionMinuteSnapshot.bucket_ts)
            .order_by(OptionMinuteSnapshot.bucket_ts)
            .all()
        )
        series = [(ts, float(s)) for ts, s in pts if s is not None]

        def spot_at(minutes):
            target = start + timedelta(minutes=minutes)
            if now < target:
                return None
            for ts, s in series:
                if ts >= target:
                    return s if (ts - target) <= timedelta(minutes=3) else None
            return None

        r.spot_15m = spot_at(15)
        r.spot_30m = spot_at(30)
        r.spot_60m = spot_at(60)
        if series:
            r.high_60m = max(s for _, s in series)
            r.low_60m = min(s for _, s in series)
        done = now >= end or now.date() > start.date() or now.time() > dtime(15, 45)
        if done:
            r.outcome_done = True
        updated += 1
    if updated:
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
    return updated


def _row_dict(r: OptionDecisionLog) -> dict:
    f = lambda v: float(v) if v is not None else None
    return {
        "id": r.id, "decided_at": r.decided_at.isoformat(), "spot": f(r.spot),
        "raw_score": r.raw_score, "raw_bias": r.raw_bias, "bias": r.bias,
        "pending_bias": r.pending_bias, "pending_count": r.pending_count,
        "confidence": r.confidence, "metrics": r.metrics, "signals": r.signals,
        "opportunities": r.opportunities, "spike_alerts": r.spike_alerts,
        "spot_15m": f(r.spot_15m), "spot_30m": f(r.spot_30m), "spot_60m": f(r.spot_60m),
        "high_60m": f(r.high_60m), "low_60m": f(r.low_60m), "outcome_done": r.outcome_done,
    }


def get_decisions(db: Session, day: date) -> List[dict]:
    start = datetime.combine(day, dtime.min)
    rows = (
        db.query(OptionDecisionLog)
        .filter(OptionDecisionLog.decided_at >= start,
                OptionDecisionLog.decided_at < start + timedelta(days=1))
        .order_by(OptionDecisionLog.decided_at)
        .all()
    )
    return [_row_dict(r) for r in rows]


def get_stats(db: Session, days: int, now: datetime) -> dict:
    since = now - timedelta(days=days)
    rows = (
        db.query(OptionDecisionLog)
        .filter(OptionDecisionLog.decided_at >= since)
        .order_by(OptionDecisionLog.decided_at)
        .all()
    )

    bias_stats: Dict[str, dict] = {}
    for r in rows:
        if r.spot_30m is None or not r.spot:
            continue
        move = (float(r.spot_30m) - float(r.spot)) / float(r.spot) * 100.0
        if r.bias == "BULLISH":
            hit = move > 0
        elif r.bias == "BEARISH":
            hit = move < 0
        else:
            hit = abs(move) <= NEUTRAL_HIT_PCT
        s = bias_stats.setdefault(r.bias or "?", {"count": 0, "hits": 0, "sum_move": 0.0})
        s["count"] += 1
        s["hits"] += 1 if hit else 0
        s["sum_move"] += move
    for s in bias_stats.values():
        s["hit_rate_pct"] = round(s["hits"] / s["count"] * 100, 1) if s["count"] else None
        s["avg_move_30m_pct"] = round(s["sum_move"] / s["count"], 3) if s["count"] else None
        del s["sum_move"]

    seen = set()
    opp_stats: Dict[str, dict] = {}
    conf_stats: Dict[str, dict] = {}
    for r in rows:
        if not r.outcome_done or r.high_60m is None or r.low_60m is None:
            continue
        hi, lo = float(r.high_60m), float(r.low_60m)
        for o in (r.opportunities or []):
            key = (r.decided_at.date(), o.get("type"), o.get("strike"), o.get("pe_strike"))
            if key in seen:
                continue            # count each opportunity once per day (first time shown)
            seen.add(key)
            t, k = o.get("type"), o.get("strike")
            if t == "SELL CE":
                held = hi < k
            elif t == "SELL PE":
                held = lo > k
            elif t == "STRANGLE":
                held = hi < k and lo > o.get("pe_strike")
            else:
                continue
            for bucket, name in ((opp_stats, t),
                                 (conf_stats, "<65" if o["confidence"] < 65 else "65-79" if o["confidence"] < 80 else "80+")):
                s = bucket.setdefault(name, {"count": 0, "held": 0})
                s["count"] += 1
                s["held"] += 1 if held else 0
    for bucket in (opp_stats, conf_stats):
        for s in bucket.values():
            s["hold_rate_pct"] = round(s["held"] / s["count"] * 100, 1) if s["count"] else None

    return {
        "days": days,
        "decisions_total": len(rows),
        "bias_accuracy_30m": bias_stats,
        "opportunities_held_60m": opp_stats,
        "by_confidence": conf_stats,
        "note": ("Bias hit = NIFTY moved the predicted way 30 min later (NEUTRAL: moved < "
                 f"{NEUTRAL_HIT_PCT}%). Opportunity 'held' = NIFTY never crossed the sold strike "
                 "within 60 min."),
    }
