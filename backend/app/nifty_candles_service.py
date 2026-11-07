"""
nifty_candles_service.py — downloads NIFTY 50 index 5-minute candles from
Angel One's getCandleData API and stores them in nifty_candles_5min, for
backtesting.

Same conventions as daily_candles_service.py:
  - Angel REST calls go through angel_client.request_with_retry (auto relogin).
  - 0.6 s throttle between calls + retry with backoff on rate-limit errors.
  - Incremental: first run pulls ~3 years; later runs pull only what is missing.
  - Inserts are idempotent (ON CONFLICT DO NOTHING).

Angel One allows at most ~100 days of data per FIVE_MINUTE request, so the
range is cut into 90-day chunks, OLDEST FIRST. If a chunk fails the run stops,
so a gap can never be skipped over (the next run resumes from the last
stored candle).

Timestamps are stored as naive IST wall-clock time of the candle START
(e.g. 09:15 = the 09:15-09:20 candle). Candles still forming (not yet
closed) are never stored.

Index volume: NIFTY is an index, so Angel normally returns 0 volume.
"""

import time
from datetime import datetime, timedelta

from sqlalchemy import BigInteger, Column, DateTime, Integer, Numeric, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.database import Base
from app.models import now_ist_naive
from app import angel_client
from app.config import settings

CANDLE_DATA_URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData"

SYMBOL = "NIFTY"
EXCHANGE = "NSE"
NIFTY_TOKEN = "99926000"       # Angel's historical-data token for NIFTY 50 (not the 26000 used by the websocket)
INTERVAL = "FIVE_MINUTE"
CANDLE_MINUTES = 5

CHUNK_DAYS = 90                # Angel's limit for 5-minute data is 100 days per request
DEFAULT_YEARS = 3
THROTTLE_SECONDS = 0.6
RATE_LIMIT_RETRY_DELAYS = [3, 8, 15]
INSERT_BATCH = 5000


class NiftyCandle5Min(Base):
    __tablename__ = "nifty_candles_5min"
    __table_args__ = (UniqueConstraint("symbol", "candle_ts", name="uq_nifty5m_symbol_ts"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False, default=SYMBOL)
    candle_ts = Column(DateTime, nullable=False, index=True)
    open = Column(Numeric(12, 2), nullable=False)
    high = Column(Numeric(12, 2), nullable=False)
    low = Column(Numeric(12, 2), nullable=False)
    close = Column(Numeric(12, 2), nullable=False)
    volume = Column(BigInteger, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


def _is_rate_limit_error(error: Exception) -> bool:
    message = str(error).lower()
    return "exceeding access rate" in message or "too many requests" in message or "ab1021" in message


def _fetch_chunk(db: Session, from_dt: datetime, to_dt: datetime) -> list:
    payload = {
        "exchange": EXCHANGE,
        "symboltoken": NIFTY_TOKEN,
        "interval": INTERVAL,
        "fromdate": from_dt.strftime("%Y-%m-%d %H:%M"),
        "todate": to_dt.strftime("%Y-%m-%d %H:%M"),
    }
    response = angel_client.request_with_retry(
        db,
        client_code=settings.angel_client_code,
        mpin=settings.angel_mpin,
        api_key=settings.angel_api_key,
        totp_secret=settings.angel_totp_secret,
        method="POST",
        url=CANDLE_DATA_URL,
        json=payload,
    )
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
    body = response.json()
    if not body.get("status"):
        raise RuntimeError(f"Angel API error: {body.get('message')} ({body.get('errorcode')})")

    out = []
    for c in body.get("data") or []:
        try:
            # e.g. "2024-01-15T09:15:00+05:30" -> keep the IST wall-clock part
            ts = datetime.fromisoformat(str(c[0]).replace(" ", "T")[:19])
            out.append({
                "symbol": SYMBOL,
                "candle_ts": ts,
                "open": c[1], "high": c[2], "low": c[3], "close": c[4],
                "volume": int(c[5] or 0),
                "created_at": datetime.utcnow(),
            })
        except (IndexError, ValueError, TypeError):
            continue
    return out


def _fetch_chunk_with_retry(db: Session, from_dt: datetime, to_dt: datetime) -> list:
    last_error = None
    for delay in [0] + RATE_LIMIT_RETRY_DELAYS:
        if delay:
            time.sleep(delay)
        try:
            return _fetch_chunk(db, from_dt, to_dt)
        except Exception as e:
            last_error = e
            if not _is_rate_limit_error(e):
                raise
    raise RuntimeError(f"Still rate-limited after {len(RATE_LIMIT_RETRY_DELAYS)} retries: {last_error}")


def _store(db: Session, candles: list) -> int:
    added = 0
    for i in range(0, len(candles), INSERT_BATCH):
        stmt = pg_insert(NiftyCandle5Min.__table__).values(candles[i:i + INSERT_BATCH])
        stmt = stmt.on_conflict_do_nothing(constraint="uq_nifty5m_symbol_ts")
        added += db.execute(stmt).rowcount or 0
    db.commit()
    return added


def sync_nifty_5min(db: Session, years: float = DEFAULT_YEARS, days: int | None = None) -> dict:
    """
    Makes sure the table covers [now - years (or days), now] with no gaps:
      1) BACKFILL: if the oldest stored candle is newer than the target start,
         fetch the older history, going backwards (newest chunk first) so the
         stored data is always one contiguous block even if a run is interrupted.
      2) FORWARD: fetch everything after the newest stored candle.
    Safe to re-run any time.
    """
    now = now_ist_naive()
    lookback_days = days if days else int(years * 365)
    target_start = datetime.combine((now - timedelta(days=lookback_days)).date(), datetime.min.time())
    cutoff = now - timedelta(minutes=CANDLE_MINUTES)   # only closed candles
    session_end = now.replace(hour=15, minute=30, second=0, microsecond=0)

    first_ts, last_ts = (
        db.query(func.min(NiftyCandle5Min.candle_ts), func.max(NiftyCandle5Min.candle_ts))
        .filter(NiftyCandle5Min.symbol == SYMBOL)
        .one()
    )

    chunks = 0
    added = 0

    # ---- 1) backfill older history (newest chunk first) ----
    if first_ts is None:
        back_end = None                      # empty table: everything is "forward" below
        fwd_start = target_start
    else:
        fwd_start = last_ts + timedelta(minutes=CANDLE_MINUTES)
        back_end = first_ts - timedelta(minutes=CANDLE_MINUTES)

    if back_end is not None and back_end > target_start + timedelta(days=1):
        while back_end > target_start:
            chunk_start = max(back_end - timedelta(days=CHUNK_DAYS), target_start)
            candles = _fetch_chunk_with_retry(db, chunk_start, back_end)
            chunks += 1
            added += _store(db, candles)
            print(f"  backfill chunk {chunks}: {chunk_start:%Y-%m-%d} -> {back_end:%Y-%m-%d}  "
                  f"fetched {len(candles)} candles (total new so far: {added})")
            back_end = chunk_start - timedelta(minutes=CANDLE_MINUTES)
            time.sleep(THROTTLE_SECONDS)

    # ---- 2) forward: from newest stored candle (or target start) up to now ----
    chunk_start = fwd_start
    while chunk_start <= now:
        chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS), session_end)
        if chunk_end <= chunk_start:
            chunk_end = chunk_start + timedelta(hours=6)
        candles = _fetch_chunk_with_retry(db, chunk_start, chunk_end)
        candles = [c for c in candles if c["candle_ts"] <= cutoff]
        chunks += 1
        added += _store(db, candles)
        print(f"  forward chunk {chunks}: {chunk_start:%Y-%m-%d} -> {chunk_end:%Y-%m-%d}  "
              f"fetched {len(candles)} candles (total new so far: {added})")
        chunk_start = chunk_end + timedelta(minutes=1)
        time.sleep(THROTTLE_SECONDS)
        if chunk_end >= session_end:
            break

    return {"status": "ok", "chunks": chunks, "candles_added": added,
            "target_start": str(target_start), "to": str(now)}


def verify(db: Session) -> dict:
    """Overall stats + trading days that look incomplete (a full session = 75 candles)."""
    row = db.execute(text(
        "SELECT COUNT(*), MIN(candle_ts), MAX(candle_ts), COUNT(DISTINCT candle_ts::date) "
        "FROM nifty_candles_5min WHERE symbol = :s"), {"s": SYMBOL}).one()
    short = db.execute(text(
        "SELECT candle_ts::date AS d, COUNT(*) AS n FROM nifty_candles_5min "
        "WHERE symbol = :s GROUP BY candle_ts::date HAVING COUNT(*) <> 75 ORDER BY d"),
        {"s": SYMBOL}).fetchall()
    return {
        "total_candles": int(row[0]), "first": row[1], "last": row[2], "trading_days": int(row[3]),
        "days_not_75_candles": [(str(r.d), int(r.n)) for r in short],
    }
