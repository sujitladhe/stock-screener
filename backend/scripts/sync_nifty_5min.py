"""
scripts/sync_nifty_5min.py — downloads NIFTY 50 5-minute candles from Angel One
and stores them in the nifty_candles_5min table (for backtesting).

RUN:
    cd backend
    python -m scripts.sync_nifty_5min --days 10     # small test first
    python -m scripts.sync_nifty_5min               # full 3 years (first run)
    python -m scripts.sync_nifty_5min --years 5     # a longer history
    python -m scripts.sync_nifty_5min --verify      # just print stats / gaps

Re-running is safe: it only fetches what is missing after the last stored candle.

CRON (daily after close, 16:45 IST = 11:15 UTC, Mon-Fri):
    15 11 * * 1-5 cd /home/ubuntu/Screener_project/backend && venv/bin/python -m scripts.sync_nifty_5min >> /var/log/screener_nifty_5min.log 2>&1
"""

import argparse
import sys
from datetime import datetime

from app.database import SessionLocal
from app.nifty_candles_service import sync_nifty_5min, verify


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--years", type=float, default=3, help="History length for the first run (default 3)")
    p.add_argument("--days", type=int, default=None, help="First run only: use N days instead of years (testing)")
    p.add_argument("--verify", action="store_true", help="Only print stats and incomplete days")
    args = p.parse_args()

    db = SessionLocal()
    try:
        if not args.verify:
            print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Starting NIFTY 5-min candle sync...")
            summary = sync_nifty_5min(db, years=args.years, days=args.days)
            print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Done: {summary}")

        v = verify(db)
        print("\nStored data:")
        print(f"  Candles: {v['total_candles']}   Trading days: {v['trading_days']}")
        print(f"  First: {v['first']}   Last: {v['last']}")
        bad = v["days_not_75_candles"]
        if bad:
            print(f"  Days without exactly 75 candles ({len(bad)}) - holidays, half-days "
                  f"(e.g. Muhurat) or today's partial session are expected:")
            for d, n in bad[:40]:
                print(f"    {d}: {n}")
            if len(bad) > 40:
                print(f"    ... and {len(bad) - 40} more")
    except Exception as e:
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] FAILED: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
