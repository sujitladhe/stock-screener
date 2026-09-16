"""
scripts/sync_instruments.py — run this once a day (~8:40 AM, per the
architecture doc) to refresh the shared NSE equity instrument list.

RUN MANUALLY (for testing):
    cd backend
    python -m scripts.sync_instruments

SCHEDULE VIA CRON (on your EC2 instance):
    crontab -e
    # then add a line like:
    40 8 * * 1-5 cd /path/to/backend && /path/to/venv/bin/python -m scripts.sync_instruments >> /var/log/screener_instruments_sync.log 2>&1

    The "1-5" means Monday-Friday only (no point running on weekends
    when the market's closed and the file won't have changed).
"""

import sys
from datetime import datetime

from app.database import SessionLocal
from app.config import settings
from app.instruments_service import sync_instruments


def main():
    print(f"[{datetime.now()}] Starting instrument sync...")
    db = SessionLocal()
    try:
        summary = sync_instruments(db, app_key=settings.ventura_service_app_key)
        print(f"[{datetime.now()}] Sync complete: {summary}")
    except Exception as e:
        print(f"[{datetime.now()}] Sync FAILED: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
