"""
history.py — the Guidance Engine's MEMORY.

Every minute during market hours the router takes a snapshot of the option
chain (price, open interest, volume for every strike within +/-1500 points of
NIFTY) and stores it here:

  1. in memory (a rolling list of the last ~13 hours of 1-minute "buckets"),
     so the engine can instantly compare "now" with "5 / 10 / 15 minutes ago";
  2. in the database (table option_minute_snapshot), so a server restart does
     not wipe the engine's memory — today's buckets are reloaded at startup.

Data older than RETENTION_DAYS is deleted by purge_old().

A "bucket" is a plain dict:
  {"ts": datetime (IST wall clock, seconds=0),
   "spot": float, "expiry": "YYYY-MM-DD",
   "strikes": {strike(int): {"ce_ltp","pe_ltp","ce_oi","pe_oi","ce_vol","pe_vol"}}}

Everything in this module runs on the single asyncio thread (the DB work is
pushed to a worker thread by the router with its own session), so no locking
is needed.
"""

import logging
from collections import deque
from datetime import datetime, date, time as dtime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.options.models import OptionMinuteSnapshot

logger = logging.getLogger(__name__)

STORE_RANGE_PTS = 1500     # strikes within +/- this many points of spot are stored
STRIKE_STEP = 50
MAX_BUCKETS = 800          # ~13 hours of 1-minute buckets (a trading day is 375)
MIN_WINDOW_MIN = 4         # shortest look-back the engine will accept
RETENTION_DAYS = 10        # 1-minute data older than this is deleted


def _f(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class HistoryStore:
    def __init__(self):
        self.buckets: deque = deque(maxlen=MAX_BUCKETS)

    # ----- basic access ---------------------------------------------------
    def clear(self) -> None:
        self.buckets.clear()

    def add(self, bucket: dict) -> None:
        """Appends a bucket (replaces the last one if it has the same minute)."""
        if self.buckets and self.buckets[-1]["ts"] >= bucket["ts"]:
            if self.buckets[-1]["ts"] == bucket["ts"]:
                self.buckets[-1] = bucket
            return
        self.buckets.append(bucket)

    def latest(self) -> Optional[dict]:
        return self.buckets[-1] if self.buckets else None

    def recent(self, n: int) -> List[dict]:
        return list(self.buckets)[-n:]

    def minutes_of_data(self) -> int:
        if len(self.buckets) < 2:
            return 0
        return int((self.buckets[-1]["ts"] - self.buckets[0]["ts"]).total_seconds() // 60)

    def lookback(self, new: dict, minutes: int) -> Optional[Tuple[dict, int]]:
        """
        Finds the bucket from about `minutes` before `new` (same trading day).
        If the day is younger than that, uses the earliest bucket of the day,
        as long as it is at least MIN_WINDOW_MIN old. Returns (bucket, actual
        minutes between them) or None if there is not enough history yet.
        """
        target = new["ts"] - timedelta(minutes=minutes)
        day = new["ts"].date()
        chosen = None
        earliest = None
        for b in self.buckets:
            if b["ts"].date() != day:
                continue
            if earliest is None:
                earliest = b
            if b["ts"] <= target:
                chosen = b
            else:
                break
        if chosen is None:
            chosen = earliest
        if chosen is None:
            return None
        age = (new["ts"] - chosen["ts"]).total_seconds() / 60.0
        if age < MIN_WINDOW_MIN:
            return None
        return chosen, int(round(age))

    # ----- database -------------------------------------------------------
    def load_today(self, db: Session, expiry_date: date, today: date) -> int:
        """Reloads today's buckets from the DB (used at startup). Returns count."""
        start = datetime.combine(today, dtime.min)
        rows = (
            db.query(OptionMinuteSnapshot)
            .filter(OptionMinuteSnapshot.bucket_ts >= start,
                    OptionMinuteSnapshot.expiry == expiry_date)
            .order_by(OptionMinuteSnapshot.bucket_ts, OptionMinuteSnapshot.strike)
            .all()
        )
        self.buckets.clear()
        cur = None
        for r in rows:
            if cur is None or cur["ts"] != r.bucket_ts:
                if cur is not None:
                    self.buckets.append(cur)
                cur = {
                    "ts": r.bucket_ts,
                    "spot": _f(r.spot) or 0.0,
                    "expiry": r.expiry.isoformat(),
                    "strikes": {},
                }
            cur["strikes"][r.strike] = {
                "ce_ltp": _f(r.ce_ltp), "pe_ltp": _f(r.pe_ltp),
                "ce_oi": _i(r.ce_oi), "pe_oi": _i(r.pe_oi),
                "ce_vol": _i(r.ce_volume), "pe_vol": _i(r.pe_volume),
            }
        if cur is not None:
            self.buckets.append(cur)
        return len(self.buckets)


def build_bucket(snapshot: dict, ts: datetime) -> Optional[dict]:
    """Turns a live option_stream snapshot into a history bucket."""
    spot = snapshot.get("spot") or 0.0
    expiry = snapshot.get("expiry")
    if spot <= 0 or not expiry:
        return None
    strikes: Dict[int, dict] = {}
    for strike, side in (snapshot.get("strikes") or {}).items():
        strike = int(strike)
        if abs(strike - spot) > STORE_RANGE_PTS:
            continue
        ce = side.get("ce") or {}
        pe = side.get("pe") or {}
        strikes[strike] = {
            "ce_ltp": ce.get("ltp"), "pe_ltp": pe.get("ltp"),
            "ce_oi": ce.get("oi"), "pe_oi": pe.get("oi"),
            "ce_vol": ce.get("volume"), "pe_vol": pe.get("volume"),
        }
    if not strikes:
        return None
    return {"ts": ts, "spot": float(spot), "expiry": expiry, "strikes": strikes}


def persist_bucket(db: Session, bucket: dict) -> int:
    """Writes one bucket to option_minute_snapshot (safe to call twice)."""
    expiry = date.fromisoformat(bucket["expiry"])
    rows = [
        {
            "bucket_ts": bucket["ts"],
            "expiry": expiry,
            "strike": int(strike),
            "spot": round(bucket["spot"], 2),
            "ce_ltp": e.get("ce_ltp"), "pe_ltp": e.get("pe_ltp"),
            "ce_oi": e.get("ce_oi"), "pe_oi": e.get("pe_oi"),
            "ce_volume": e.get("ce_vol"), "pe_volume": e.get("pe_vol"),
        }
        for strike, e in bucket["strikes"].items()
    ]
    if not rows:
        return 0
    stmt = pg_insert(OptionMinuteSnapshot).values(rows).on_conflict_do_nothing(
        constraint="uq_option_minute_ts_expiry_strike"
    )
    try:
        db.execute(stmt)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return len(rows)


def purge_old(db: Session, now: datetime) -> int:
    cutoff = now - timedelta(days=RETENTION_DAYS)
    try:
        n = (
            db.query(OptionMinuteSnapshot)
            .filter(OptionMinuteSnapshot.bucket_ts < cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
        return n
    except Exception:
        db.rollback()
        raise


# One shared store for the whole app.
history = HistoryStore()
