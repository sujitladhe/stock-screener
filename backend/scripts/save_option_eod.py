"""
EOD snapshot + daily summary saver.
Run at 15:30 IST (10:00 UTC) after market close.

Cron (root's crontab):
  0 10 * * 1-5  cd /home/ubuntu/Screener_project/backend && python -m scripts.save_option_eod

Usage:
  python -m scripts.save_option_eod
"""

import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    from app.database import SessionLocal
    from app.options.eod_job import save_eod_snapshot, save_daily_summary

    db = SessionLocal()
    try:
        snap    = save_eod_snapshot(db)
        summary = save_daily_summary(db)
        logger.info(f"EOD snapshot: {snap}")
        logger.info(f"Daily summary: {summary}")
    except Exception as exc:
        logger.error(f"EOD save failed: {exc}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
