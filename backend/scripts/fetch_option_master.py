"""
Daily instrument master refresh.
Run at 09:00 IST (03:30 UTC) before market open.

Cron (root's crontab):
  30 3 * * 1-5  cd /home/ubuntu/Screener_project/backend && python -m scripts.fetch_option_master

Usage:
  python -m scripts.fetch_option_master
  python -m scripts.fetch_option_master --spot 22500
"""

import argparse
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Refresh NIFTY option instrument master")
    parser.add_argument("--spot", type=float, default=None,
                        help="Current NIFTY spot price (optional; filters ATM±40 when provided)")
    args = parser.parse_args()

    from app.database import SessionLocal
    from app.options.instrument_master import fetch_and_store_instrument_master

    db = SessionLocal()
    try:
        result = fetch_and_store_instrument_master(db, spot_price=args.spot)
        logger.info(
            f"Done. Tokens: {result['count']}, "
            f"Expiries: {[e.isoformat() for e in result['expiries']]}, "
            f"ATM: {result['atm']}"
        )
    except Exception as exc:
        logger.error(f"Failed: {exc}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
