"""
instruments_service.py — pulls Ventura's daily instrument master list
and syncs it into our shared `instruments` table.

Filtering rule (confirmed against a real sample file): we only keep
rows where exchange == 'NSE' and instrument == 'EQ' — mainboard equity
only. This deliberately excludes NFO/BFO options & futures, SME stocks
(SM/ST), trade-to-trade equity (BE/BZ), InvITs (IV), and REITs (RR).

Sync logic (matches the architecture doc's requirement to detect
additions/removals, not just overwrite blindly):
  - Every EQ/NSE row in today's file: insert if new, otherwise just
    update last_synced_at (and reactivate if it had been marked
    inactive before, e.g. a stock that got relisted).
  - Any instrument already in our DB as active, but NOT present in
    today's file: mark is_active = False (soft delete, not a hard
    delete, so old references to it don't break).
"""

import gzip
import io
from datetime import datetime

import requests
from sqlalchemy.orm import Session

from app.models import Instrument

INSTRUMENTS_URL = "https://easeapi.venturasecurities.com/instrument/v1/instruments"

KEEP_EXCHANGE = "NSE"
KEEP_INSTRUMENT_TYPE = "EQ"


def download_instruments_csv(app_key: str) -> str:
    """Downloads the instruments file and returns it as decoded text."""
    headers = {"x-app-key": app_key}
    response = requests.get(INSTRUMENTS_URL, headers=headers, timeout=60)

    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to download instruments — status {response.status_code}: {response.text[:500]}"
        )

    content = response.content
    if content[:2] == b"\x1f\x8b":  # gzip magic bytes, in case it arrives still compressed
        content = gzip.decompress(content)

    return content.decode("utf-8", errors="replace")


def parse_and_filter(csv_text: str) -> list[dict]:
    """
    Parses the CSV text and returns only real NSE/EQ stock rows.
    Uses the standard library csv module rather than pandas, since this
    is a simple flat-file parse and keeps dependencies lighter.

    IMPORTANT: exchange=='NSE' and instrument=='EQ' alone are NOT
    enough — indices like "Nifty 50" and "India VIX" also carry those
    same two values in Ventura's file. They're distinguished by the
    segment field: real equity has segment=='NSE', indices have
    segment=='Indices'. This was missed in an earlier version of this
    filter (caught via the Angel One symbol-mapping step, where every
    unmatched symbol turned out to be an index) — segment=='NSE' is
    now a required condition, not optional.
    """
    import csv as csv_module

    reader = csv_module.DictReader(io.StringIO(csv_text))
    rows = []
    for row in reader:
        if (
            row.get("exchange") == KEEP_EXCHANGE
            and row.get("instrument") == KEEP_INSTRUMENT_TYPE
            and row.get("segment") == KEEP_EXCHANGE  # i.e. segment == "NSE", excludes "Indices"
        ):
            rows.append(row)
    return rows


def sync_instruments(db: Session, app_key: str) -> dict:
    """
    Runs the full daily sync: download -> filter -> upsert -> mark
    missing ones inactive. Returns a summary dict for logging.
    """
    csv_text = download_instruments_csv(app_key)
    filtered_rows = parse_and_filter(csv_text)

    now = datetime.utcnow()
    seen_keys = set()  # (exchange, exchange_token) pairs present in today's file

    inserted = 0
    updated = 0
    reactivated = 0

    for row in filtered_rows:
        key = (row["exchange"], row["exchange_token"])
        seen_keys.add(key)

        existing = (
            db.query(Instrument)
            .filter_by(exchange=row["exchange"], exchange_token=row["exchange_token"])
            .first()
        )

        if existing:
            existing.trading_symbol = row["trading_symbol"]
            existing.name = row.get("name")
            existing.segment = row.get("segment")
            existing.tick_size = _safe_float(row.get("tick_size"))
            existing.lot_size = _safe_int(row.get("lot_size"))
            existing.last_synced_at = now
            if not existing.is_active:
                existing.is_active = True
                reactivated += 1
            else:
                updated += 1
        else:
            db.add(Instrument(
                exchange=row["exchange"],
                exchange_token=row["exchange_token"],
                trading_symbol=row["trading_symbol"],
                name=row.get("name"),
                instrument_type=row["instrument"],
                segment=row.get("segment"),
                tick_size=_safe_float(row.get("tick_size")),
                lot_size=_safe_int(row.get("lot_size")),
                is_active=True,
                first_seen_at=now,
                last_synced_at=now,
            ))
            inserted += 1

    # Mark anything active in our DB but absent from today's file as
    # no longer active (likely delisted or instrument type changed).
    deactivated = 0
    currently_active = db.query(Instrument).filter_by(is_active=True).all()
    for instrument in currently_active:
        if (instrument.exchange, instrument.exchange_token) not in seen_keys:
            instrument.is_active = False
            deactivated += 1

    db.commit()

    return {
        "total_in_file": len(filtered_rows),
        "inserted": inserted,
        "updated": updated,
        "reactivated": reactivated,
        "deactivated": deactivated,
    }


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
