"""
scripts/sync_daily_candles.py — daily job to fetch and store OHLCV candle
data for all NSE/EQ stocks via Angel One's getCandleData API.

HOW IT WORKS (incremental):
  - First run per stock  → fetches ~365 trading days of history
  - Subsequent runs      → fetches only days missing since last stored candle
  - Already up to date   → skipped (0 API calls for that stock)

This means:
  - First ever run across all ~2,655 stocks: expect 25-45 minutes
    (same rate-limit profile as sync_historical_averages.py)
  - Daily runs after that: a few minutes at most (1-2 candles per stock)

RUN MANUALLY (for testing a small batch first):
    cd backend
    python -m scripts.sync_daily_candles --limit 10

RUN MANUALLY (full run):
    cd backend
    python -m scripts.sync_daily_candles

SCHEDULE VIA CRON — run after market close, e.g. 4:30 PM IST daily:
    30 11 * * 1-5 cd /path/to/backend && venv/bin/python -m scripts.sync_daily_candles >> /var/log/screener_daily_candles.log 2>&1

    (11:00 UTC = 16:30 IST; 1-5 = Mon-Fri only)

NOTES:
  - Requires the instruments table to be populated (run sync_instruments.py first).
  - Requires angel_symbol_token to be mapped (run sync_angel_mapping.py first).
  - Re-running on the same day is safe — existing candles are skipped via
    ON CONFLICT DO NOTHING; already-complete stocks are skipped before any API call.
"""

import argparse
import sys
from datetime import datetime

from app.database import SessionLocal
from app.daily_candles_service import fetch_and_store_all


def main():
    parser = argparse.ArgumentParser(description="Sync daily candle data from Angel One.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N instruments (useful for testing).",
    )
    args = parser.parse_args()

    print(
        f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Starting daily candle sync"
        + (f" (limit={args.limit})" if args.limit else " (all stocks)")
        + "..."
    )

    db = SessionLocal()
    try:
        summary = fetch_and_store_all(db, limit=args.limit)

        print(
            f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Done. "
            f"Attempted: {summary['total_attempted']}, "
            f"Updated: {summary['updated_count']}, "
            f"Already up-to-date: {summary['skipped_count']}, "
            f"Failed: {summary['failed_count']}"
        )

        if summary["failed"]:
            print("Failed symbols:")
            for f in summary["failed"]:
                print(f"  - {f['symbol']}: {f['error']}")

        if summary["failed_count"] > summary["total_attempted"] * 0.05:
            print(
                "WARNING: failure rate > 5% — investigate before running scans on today's data.",
                file=sys.stderr,
            )

    except Exception as e:
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Job FAILED entirely: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
