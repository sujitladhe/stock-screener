"""
Fetches the Angel One NFO Instrument Master (public URL, no auth required).
Filters NIFTY weekly option contracts for the current + next expiry,
stores them in option_instrument_master table, and returns the token list
needed for the WebSocket subscription.

Run once daily before market open (9:00 AM cron via scripts/fetch_option_master.py).
Also called automatically on app startup if the table is empty.
"""

import requests
import logging
from datetime import datetime, date
from typing import List, Optional
from sqlalchemy.orm import Session

from app.options.models import OptionInstrumentMaster

logger = logging.getLogger(__name__)

# Public URL — no auth needed
INSTRUMENT_MASTER_URL = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)

UNDERLYING   = "NIFTY"
STRIKE_STEP  = 50     # NIFTY strike gap (₹50)
STRIKE_RANGE = 40     # ATM ± 40 strikes → 81 strikes per side × 2 = 162 contracts per expiry
NUM_EXPIRIES = 2      # current + next weekly expiry


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_expiry(expiry_str: str) -> Optional[date]:
    """'29OCT2024' → date(2024, 10, 29)"""
    try:
        return datetime.strptime(expiry_str.strip(), "%d%b%Y").date()
    except Exception:
        return None


def _parse_strike(strike_raw: str) -> int:
    """
    Angel One master stores strike as actual_strike × 100.
    e.g. '2250000.000000' → 22500
    """
    val = float(strike_raw)
    if val > 100_000:
        return int(round(val / 100))
    return int(val)


# ---------------------------------------------------------------------------
# Main fetch + store
# ---------------------------------------------------------------------------

def fetch_and_store_instrument_master(
    db: Session,
    spot_price: Optional[float] = None,
) -> dict:
    """
    Download NFO master, filter NIFTY options for current + next expiry,
    upsert into option_instrument_master.

    Args:
        db:          SQLAlchemy session
        spot_price:  Current NIFTY spot. When provided, only ATM ± STRIKE_RANGE
                     strikes are stored. When None, all strikes are stored.

    Returns:
        {tokens: [str], expiries: [date], atm: int|None, count: int}
    """
    logger.info("Fetching NFO instrument master from Angel One...")
    try:
        resp = requests.get(INSTRUMENT_MASTER_URL, timeout=30)
        resp.raise_for_status()
        all_instruments = resp.json()
    except Exception as exc:
        logger.error(f"Instrument master download failed: {exc}")
        raise

    today = date.today()

    # Filter: NFO exchange, OPTIDX type, NIFTY name (excludes BANKNIFTY, FINNIFTY …)
    nifty_opts = [
        i for i in all_instruments
        if i.get("exch_seg") == "NFO"
        and i.get("instrumenttype") == "OPTIDX"
        and i.get("name") == UNDERLYING
    ]

    # Collect distinct future expiries
    future_expiries = sorted({
        exp for i in nifty_opts
        if (exp := _parse_expiry(i.get("expiry", ""))) and exp >= today
    })

    if not future_expiries:
        raise ValueError("No future NIFTY expiries found in instrument master.")

    target_expiries = future_expiries[:NUM_EXPIRIES]
    target_exp_strs = {e.strftime("%d%b%Y").upper() for e in target_expiries}
    logger.info(f"Target expiries: {target_expiries}")

    # Determine ATM for strike-range filtering
    atm: Optional[int] = None
    if spot_price is not None:
        atm = int(round(spot_price / STRIKE_STEP) * STRIKE_STEP)

    records: List[OptionInstrumentMaster] = []

    for inst in nifty_opts:
        if inst.get("expiry", "").upper() not in target_exp_strs:
            continue
        try:
            token  = inst["token"]
            symbol = inst["symbol"]
            strike = _parse_strike(inst["strike"])
            expiry = _parse_expiry(inst["expiry"])
            opt_type = "CE" if symbol.endswith("CE") else "PE"
            lot_size = int(inst.get("lotsize", 25))

            # ATM ± STRIKE_RANGE filter (only when spot provided)
            if atm is not None and abs(strike - atm) > STRIKE_RANGE * STRIKE_STEP:
                continue

            records.append(OptionInstrumentMaster(
                token=token,
                symbol=symbol,
                name=UNDERLYING,
                strike=strike,
                expiry=expiry,
                option_type=opt_type,
                lot_size=lot_size,
                fetched_at=datetime.utcnow(),
            ))
        except Exception as e:
            logger.warning(f"Skipping instrument {inst.get('symbol')}: {e}")

    # Replace table (fresh master each run)
    try:
        db.query(OptionInstrumentMaster).delete()
        db.bulk_save_objects(records)
        db.commit()
        logger.info(f"Stored {len(records)} NIFTY option instruments.")
    except Exception as exc:
        db.rollback()
        logger.error(f"DB write failed: {exc}")
        raise

    return {
        "tokens": [r.token for r in records],
        "expiries": target_expiries,
        "atm": atm,
        "count": len(records),
    }


# ---------------------------------------------------------------------------
# Helpers for the stream service
# ---------------------------------------------------------------------------

def get_tokens_for_subscription(db: Session) -> List[str]:
    """All stored tokens — pass directly to Angel One WebSocket subscribe."""
    return [r.token for r in db.query(OptionInstrumentMaster.token).all()]


def get_strike_map(db: Session) -> dict:
    """
    Returns {token: {strike, option_type, expiry_iso, lot_size}}
    Used by option_stream.py to translate incoming WebSocket ticks.
    """
    rows = db.query(OptionInstrumentMaster).all()
    return {
        r.token: {
            "strike":      r.strike,
            "option_type": r.option_type,
            "expiry":      r.expiry.isoformat(),
            "lot_size":    r.lot_size,
        }
        for r in rows
    }


def get_active_expiries(db: Session) -> List[date]:
    """Sorted list of expiries currently in the master table."""
    rows = (
        db.query(OptionInstrumentMaster.expiry)
        .distinct()
        .order_by(OptionInstrumentMaster.expiry)
        .all()
    )
    return [r.expiry for r in rows]
