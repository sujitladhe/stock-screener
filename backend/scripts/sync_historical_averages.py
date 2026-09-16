"""
scripts/sync_historical_averages.py — the real nightly job. Run this
via cron AFTER sync_instruments.py and sync_angel_mapping.py, since it
depends on both (needs the current instrument list, and each
instrument's Angel symboltoken).

RUN MANUALLY (for testing):
    cd backend
    python -m scripts.sync_historical_averages

SCHEDULE VIA CRON — WEEKLY, not daily. The averages only need
refreshing once a week (the same computed value is used for
comparison all week) — unlike sync_instruments.py and
sync_angel_mapping.py, which should stay on a daily cadence since
they're cheap and the stock universe itself can change any day.

Example: run every Saturday at 5 AM (markets closed, so no rush
relative to market open, and it won't compete with any weekday jobs):
    0 5 * * 6 cd /path/to/backend && venv/bin/python -m scripts.sync_historical_averages >> /var/log/screener_historical_averages.log 2>&1

    (Given ~2,655 stocks with occasional rate-limit retries, expect
    this to take 25-45+ minutes depending on how much backoff kicks
    in — confirmed from real runs, not just the throttle math.)
"""

import sys
from datetime import datetime

from app.database import SessionLocal
from app.historical_averages_service import compute_and_store_all


def main():
    print(f"[{datetime.now()}] Starting historical averages computation "
          f"(will skip stocks already computed today, in case this is a resume)...")
    db = SessionLocal()
    try:
        summary = compute_and_store_all(db)
        print(f"[{datetime.now()}] Done. Attempted: {summary['total_attempted']}, "
              f"Succeeded: {summary['succeeded_count']}, Failed: {summary['failed_count']}")

        if summary["failed"]:
            print("Failed symbols:")
            for f in summary["failed"]:
                print(f"  - {f['symbol']}: {f['error']}")

        if summary["failed_count"] > summary["total_attempted"] * 0.05:
            # More than 5% failed — worth a loud signal rather than
            # burying it in a log file nobody checks.
            print("WARNING: failure rate is unusually high — investigate before trusting today's averages.", file=sys.stderr)
    except Exception as e:
        print(f"[{datetime.now()}] Job FAILED entirely: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
