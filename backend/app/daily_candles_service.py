"""
daily_candles_service.py — fetches daily OHLCV candle data from Angel One
and stores it in the daily_candles table for use in DB-level scans.

Fetch strategy (incremental):
  - First run for a stock (no rows in daily_candles): fetches 365 trading days
    worth of data (~530 calendar days back with buffer).
  - Subsequent runs: fetches only from (last stored candle date + 1 day) to today.
  - Already synced today (candles_last_synced_date == today): skipped with ZERO
    API calls — this is the key fix so re-running the script on the same day
    is nearly instant regardless of what candle dates are stored.

Rate limiting follows the same pattern as historical_averages_service.py:
  - 0.6s throttle between requests (~1.67 req/sec, under Angel One's 3 req/sec cap)
  - Retry with backoff on rate-limit errors
  - Per-stock failures are logged and skipped — one bad stock won't abort the run

Why candles_last_synced_date instead of comparing last candle date to today:
  Angel One's daily candles are dated by their trading session (e.g., Monday's candle
  is "2026-10-19"). On any given day, the latest stored candle date may be yesterday
  (last trading day) even after a successful sync. Comparing that against date.today()
  would always trigger a re-fetch for every stock, making a second run just as slow
  as the first. Tracking WHEN the sync ran (not what was stored) eliminates this.
"""

import time
from datetime import date, datetime, timedelta

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models import Instrument, DailyCandle
from app import angel_client
from app.config import settings

CANDLE_DATA_URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData"

# 365 trading days ≈ 530 calendar days (accounting for weekends + ~10 holidays/yr).
# Using 550 as a comfortable buffer so we never come up short.
INITIAL_CALENDAR_DAYS_LOOKBACK = 550   # ~365 trading days

DEFAULT_THROTTLE_SECONDS = 0.6         # ~1.67 req/sec; real-world safe (see historical_averages_service.py)
RATE_LIMIT_RETRY_DELAYS = [3, 8, 15]  # seconds between retries on rate-limit hits


def _is_rate_limit_error(error: Exception) -> bool:
    message = str(error).lower()
    return "exceeding access rate" in message or "too many requests" in message or "ab1021" in message


def _fetch_candles_for_range(
    db: Session,
    symbol_token: str,
    from_date: datetime,
    to_date: datetime,
    exchange: str = "NSE",
) -> list[dict]:
    """
    Calls Angel One getCandleData for ONE_DAY candles in [from_date, to_date].
    Returns a list of dicts: {date, open, high, low, close, volume}.
    Raises RuntimeError on failure.
    """
    payload = {
        "exchange": exchange,
        "symboltoken": symbol_token,
        "interval": "ONE_DAY",
        "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
        "todate": to_date.strftime("%Y-%m-%d %H:%M"),
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

    candles = body.get("data") or []
    # Each candle: [timestamp_str, open, high, low, close, volume]
    # timestamp format: "2024-01-15 09:15"
    result = []
    for candle in candles:
        try:
            ts_str = candle[0]
            candle_date = datetime.strptime(ts_str[:10], "%Y-%m-%d").date()
            result.append({
                "date": candle_date,
                "open": candle[1],
                "high": candle[2],
                "low": candle[3],
                "close": candle[4],
                "volume": int(candle[5]),
            })
        except (IndexError, ValueError, TypeError):
            continue

    return result


def fetch_and_store_one(db: Session, instrument: Instrument, today: date) -> dict:
    """
    Fetches and stores candle data for a single instrument.

    Skip logic (zero API calls):
      - If instrument.candles_last_synced_date == today → already synced today, skip.

    Fetch logic (incremental):
      - No candles at all → fetch ~365 trading days of history
      - Has candles       → fetch from (last stored date + 1) to today

    Returns a summary dict with status: "skipped_today" | "up_to_date" | "updated" | "no_data"
    """

    # ── Fast skip: already synced today (no API call at all) ─────────────────
    if instrument.candles_last_synced_date == today:
        return {
            "symbol": instrument.trading_symbol,
            "status": "skipped_today",
            "candles_added": 0,
        }

    # ── Determine fetch window ────────────────────────────────────────────────
    last_stored = (
        db.query(func.max(DailyCandle.candle_date))
        .filter(DailyCandle.instrument_id == instrument.id)
        .scalar()
    )

    if last_stored is None:
        # First run for this stock — fetch full history
        from_date = datetime.combine(
            today - timedelta(days=INITIAL_CALENDAR_DAYS_LOOKBACK),
            datetime.min.time(),
        )
    else:
        # Incremental — fetch only what's missing
        from_date = datetime.combine(last_stored + timedelta(days=1), datetime.min.time())

    to_date = datetime.combine(today, datetime.min.time()).replace(hour=15, minute=30)

    # If from_date is already past to_date, nothing to fetch (can happen on weekends/holidays)
    if from_date > to_date:
        _mark_synced(db, instrument, today)
        return {
            "symbol": instrument.trading_symbol,
            "status": "up_to_date",
            "candles_added": 0,
        }

    # ── Fetch with rate-limit retry ───────────────────────────────────────────
    last_error = None
    candles = None
    for attempt, delay in enumerate([0] + RATE_LIMIT_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            candles = _fetch_candles_for_range(db, instrument.angel_symbol_token, from_date, to_date)
            break
        except Exception as e:
            last_error = e
            if not _is_rate_limit_error(e):
                raise
    else:
        raise RuntimeError(f"Still rate-limited after {len(RATE_LIMIT_RETRY_DELAYS)} retries: {last_error}")

    if not candles:
        # No data returned (holiday, illiquid stock, etc.) — still mark synced
        # so we don't keep hitting the API every re-run on a holiday
        _mark_synced(db, instrument, today)
        return {
            "symbol": instrument.trading_symbol,
            "status": "no_data",
            "candles_added": 0,
        }

    # ── Bulk upsert (idempotent) ──────────────────────────────────────────────
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    rows = [
        {
            "instrument_id": instrument.id,
            "trading_symbol": instrument.trading_symbol,
            "candle_date": c["date"],
            "open": c["open"],
            "high": c["high"],
            "low": c["low"],
            "close": c["close"],
            "volume": c["volume"],
            "created_at": datetime.utcnow(),
        }
        for c in candles
    ]

    stmt = pg_insert(DailyCandle.__table__).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=["instrument_id", "candle_date"])
    db.execute(stmt)

    # ── Mark this stock as synced today ──────────────────────────────────────
    _mark_synced(db, instrument, today)

    return {
        "symbol": instrument.trading_symbol,
        "status": "updated",
        "candles_added": len(candles),
        "from": str(candles[0]["date"]) if candles else None,
        "to": str(candles[-1]["date"]) if candles else None,
    }


def _mark_synced(db: Session, instrument: Instrument, today: date) -> None:
    """Sets candles_last_synced_date = today on the instrument row and commits."""
    db.execute(
        text("UPDATE instruments SET candles_last_synced_date = :d WHERE id = :id"),
        {"d": today, "id": instrument.id},
    )
    db.commit()


def fetch_and_store_all(
    db: Session,
    throttle_seconds: float = DEFAULT_THROTTLE_SECONDS,
    limit: int | None = None,
) -> dict:
    """
    Runs the daily candle sync for every active, Angel-mapped NSE/EQ instrument.

    Incremental by design:
      - Already synced today → zero API calls (instant skip per stock)
      - First run per stock  → fetches ~365 trading days
      - Subsequent runs      → fetches only missing days (typically 1–2 candles)

    limit: if set, only processes the first N instruments (useful for testing).
    """
    today = date.today()

    query = (
        db.query(Instrument)
        .filter(
            Instrument.exchange == "NSE",
            Instrument.instrument_type == "EQ",
            Instrument.is_active == True,           # noqa: E712
            Instrument.angel_symbol_token.isnot(None),
        )
        .order_by(Instrument.id)
    )

    if limit:
        query = query.limit(limit)

    instruments = query.all()

    succeeded = []
    failed = []
    skipped = 0

    for i, instrument in enumerate(instruments, start=1):
        try:
            result = fetch_and_store_one(db, instrument, today)
            if result["status"] in ("skipped_today", "up_to_date", "no_data"):
                skipped += 1
            else:
                succeeded.append(result)
        except Exception as e:
            failed.append({"symbol": instrument.trading_symbol, "error": str(e)})
                db.rollback()
        if i % 50 == 0 or i == len(instruments):
            print(
                f"  Progress: {i}/{len(instruments)} "
                f"(updated: {len(succeeded)}, skipped: {skipped}, failed: {len(failed)})"
            )

        # Only throttle when an API call was actually made (not for skipped stocks)
        # skipped_today means no API call → no need to sleep
        if result.get("status") != "skipped_today":
            time.sleep(throttle_seconds)

    return {
        "total_attempted": len(instruments),
        "updated_count": len(succeeded),
        "skipped_count": skipped,
        "failed_count": len(failed),
        "failed": failed,
    }
