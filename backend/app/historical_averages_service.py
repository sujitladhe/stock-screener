"""
historical_averages_service.py — for every mapped stock, pulls daily
candles from Angel One's getCandleData and computes:

    avg_volume_per_min = (sum of volume over N trading days) / N / 375

where N is the actual number of trading-day candles we got back,
capped at 30 (not always exactly 30 — see note on recently listed
stocks below).

Design notes:
  - We request 45 CALENDAR days back, not 30, because 30 calendar
    days only covers ~20-22 trading days after weekends and holidays.
    Requesting a wider window and then taking the most recent 30
    trading-day candles (or fewer, if the stock is newer) gives us a
    true 30-trading-day average, matching your stated formula.
  - Recently listed stocks: per your instruction, we don't enforce a
    minimum history — whatever days are available get used, and we
    divide by that actual count (trading_days_used), not a hardcoded
    30. A stock listed 5 days ago gets averaged over 5 days.
  - Rate limiting: Angel's documented cap is 3 requests/second. We
    throttle conservatively (see DEFAULT_THROTTLE_SECONDS) since forum
    reports suggest enforcement can be stricter than documented in
    practice.
  - Failures for individual stocks (API errors, no data, etc.) are
    logged and skipped — one bad stock should never abort the whole
    nightly run.
"""

import time
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Instrument, VolumeAverage
from app import angel_client
from app.config import settings

CANDLE_DATA_URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData"

CALENDAR_DAYS_LOOKBACK = 45   # wide enough buffer to guarantee ~30 trading days
MAX_TRADING_DAYS = 30         # per your formula: divide by 30 (or fewer, for new listings)
MINUTES_PER_TRADING_DAY = 375

# A real test run showed 403 "exceeding access rate" errors even at
# 0.4s spacing (2.5 req/sec), under Angel's documented 3 req/sec cap —
# confirms forum reports that real-world enforcement is stricter or
# burstier than documented. Widened the gap and added retry-with-
# backoff below rather than trusting the documented limit at face value.
DEFAULT_THROTTLE_SECONDS = 0.6   # ~1.67 req/sec
RATE_LIMIT_RETRY_DELAYS = [3, 8, 15]  # seconds to wait between retries on a rate-limit hit


def _is_rate_limit_error(error: Exception) -> bool:
    """
    Detects rate-limit errors so they get retried with backoff, rather
    than treated as a permanent failure. Angel One has been observed
    (across real runs) sending at least two different messages for
    what's functionally the same problem — checking for both rather
    than assuming there's only one phrasing.
    """
    message = str(error).lower()
    return "exceeding access rate" in message or "too many requests" in message or "ab1021" in message


def fetch_daily_volumes(db: Session, symbol_token: str, exchange: str = "NSE") -> list[float]:
    """
    Fetches daily candles for one stock and returns a list of volumes
    (most recent first), capped at MAX_TRADING_DAYS entries.
    Raises RuntimeError with a clear message on failure.
    """
    to_date = datetime.now().replace(hour=15, minute=30, second=0, microsecond=0)
    from_date = to_date - timedelta(days=CALENDAR_DAYS_LOOKBACK)

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
    if not candles:
        raise RuntimeError("No candle data returned (possibly a newly listed or illiquid stock)")

    # Each candle: [timestamp, open, high, low, close, volume].
    # Candles come back oldest-first (confirmed in our test call) —
    # reverse so most recent is first, then take up to MAX_TRADING_DAYS.
    volumes = [candle[5] for candle in candles]
    volumes.reverse()
    return volumes[:MAX_TRADING_DAYS]


def compute_and_store_one(db: Session, instrument: Instrument) -> dict:
    """
    Computes and stores the average for a single instrument.
    Retries with increasing backoff specifically on rate-limit errors
    (not on other failures — e.g. "no data" for an illiquid stock
    should fail immediately, not waste time retrying).
    """
    last_error = None
    for attempt, delay in enumerate([0] + RATE_LIMIT_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            volumes = fetch_daily_volumes(db, instrument.angel_symbol_token)
            break
        except Exception as e:
            last_error = e
            if not _is_rate_limit_error(e):
                raise  # a real error, not rate-limiting — don't retry, fail now
    else:
        raise RuntimeError(f"Still rate-limited after {len(RATE_LIMIT_RETRY_DELAYS)} retries: {last_error}")

    days_used = len(volumes)
    total_volume = sum(volumes)
    avg_volume_per_min = (total_volume / days_used) / MINUTES_PER_TRADING_DAY

    existing = db.query(VolumeAverage).filter_by(instrument_id=instrument.id).first()
    if existing:
        existing.avg_volume_per_min = avg_volume_per_min
        existing.trading_days_used = days_used
        existing.total_volume_used = total_volume
        existing.last_computed_at = datetime.utcnow()
    else:
        db.add(VolumeAverage(
            instrument_id=instrument.id,
            avg_volume_per_min=avg_volume_per_min,
            trading_days_used=days_used,
            total_volume_used=total_volume,
            last_computed_at=datetime.utcnow(),
        ))
    db.commit()

    return {
        "symbol": instrument.trading_symbol,
        "days_used": days_used,
        "avg_volume_per_min": avg_volume_per_min,
    }


def compute_and_store_all(
    db: Session,
    throttle_seconds: float = DEFAULT_THROTTLE_SECONDS,
    limit: int | None = None,
    skip_computed_today: bool = True,
) -> dict:
    """
    Runs the full nightly job: fetches + computes + stores averages
    for every active, mapped NSE/EQ instrument.

    limit: if set, only processes the first N instruments — useful for
    testing on a small batch before committing to the full ~2,655-stock
    run.

    skip_computed_today: if True (the default), instruments that
    already have a VolumeAverage row computed TODAY are skipped. This
    is what makes the job resumable — if it gets interrupted partway
    through (laptop disconnects, server restarts, etc.), re-running it
    picks up only the stocks that haven't been done yet today, instead
    of starting over from scratch. Tomorrow's run will naturally
    reprocess everyone again, since "computed today" no longer applies.
    """
    query = (
        db.query(Instrument)
        .outerjoin(VolumeAverage, VolumeAverage.instrument_id == Instrument.id)
        .filter(
            Instrument.exchange == "NSE",
            Instrument.instrument_type == "EQ",
            Instrument.is_active == True,  # noqa: E712
            Instrument.angel_symbol_token.isnot(None),
        )
    )

    if skip_computed_today:
        today = datetime.utcnow().date()
        query = query.filter(
            (VolumeAverage.id.is_(None))
            | (func.date(VolumeAverage.last_computed_at) < today)
        )

    query = query.order_by(Instrument.id)
    if limit:
        query = query.limit(limit)

    instruments = query.all()

    succeeded = []
    failed = []

    for i, instrument in enumerate(instruments, start=1):
        try:
            result = compute_and_store_one(db, instrument)
            succeeded.append(result)
        except Exception as e:
            failed.append({"symbol": instrument.trading_symbol, "error": str(e)})

        if i % 50 == 0 or i == len(instruments):
            print(f"  Progress: {i}/{len(instruments)} (succeeded: {len(succeeded)}, failed: {len(failed)})")

        time.sleep(throttle_seconds)

    return {
        "total_attempted": len(instruments),
        "succeeded_count": len(succeeded),
        "failed_count": len(failed),
        "failed": failed,  # full list, not truncated, so nothing is hidden
    }
