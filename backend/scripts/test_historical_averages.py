"""
scripts/test_historical_averages.py — runs the averages computation
on a SMALL batch (default 10 stocks) so we can verify correctness and
timing before committing to the full ~2,655-stock run, which takes
15-20 minutes.

RUN:
    cd backend
    python -m scripts.test_historical_averages
    python -m scripts.test_historical_averages --limit 25   # custom batch size
"""

import argparse

from app.database import SessionLocal
from app.historical_averages_service import compute_and_store_all


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10, help="Number of stocks to test with")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        print(f"Running historical averages computation on a test batch of {args.limit} stocks...")
        summary = compute_and_store_all(db, limit=args.limit)

        print(f"\nAttempted: {summary['total_attempted']}")
        print(f"Succeeded: {summary['succeeded_count']}")
        print(f"Failed: {summary['failed_count']}")

        if summary["failed"]:
            print("\nFailures:")
            for f in summary["failed"]:
                print(f"  - {f['symbol']}: {f['error']}")

        # Show the actual computed values for a sanity check
        from app.models import VolumeAverage, Instrument
        print("\nSample computed averages:")
        rows = (
            db.query(VolumeAverage, Instrument)
            .join(Instrument, VolumeAverage.instrument_id == Instrument.id)
            .limit(args.limit)
            .all()
        )
        for avg, inst in rows:
            print(
                f"  {inst.trading_symbol}: avg_volume_per_min={float(avg.avg_volume_per_min):.2f}, "
                f"days_used={avg.trading_days_used}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
