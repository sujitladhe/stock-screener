"""
angel_symbol_mapping.py — matches our stored Ventura NSE/EQ
instruments to Angel One's own symboltoken, needed because historical
candle data comes from Angel, not Ventura, and the two brokers use
completely different token numbering.

Observed pattern (confirmed against one stock, SBIN): Angel's `symbol`
field for NSE equity is Ventura's trading_symbol + "-EQ" suffix
(e.g. "SBIN" -> "SBIN-EQ"). This module tests that pattern against the
FULL instrument universe and reports match/no-match counts, rather
than assuming it holds everywhere — a single confirmed example isn't
enough to trust for ~2,674 stocks.
"""

import requests
from sqlalchemy.orm import Session

from app.models import Instrument

ANGEL_INSTRUMENT_MASTER_URL = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)


def fetch_angel_nse_equity_map() -> dict:
    """
    Downloads Angel's full instrument master and returns a dict of
    {symbol: token} for NSE equity rows only (symbol ending in "-EQ").
    """
    response = requests.get(ANGEL_INSTRUMENT_MASTER_URL, timeout=60)
    response.raise_for_status()
    all_instruments = response.json()

    nse_equity_map = {}
    for inst in all_instruments:
        symbol = inst.get("symbol", "")
        if inst.get("exch_seg") == "NSE" and symbol.endswith("-EQ"):
            nse_equity_map[symbol] = inst.get("token")

    return nse_equity_map


def sync_angel_symbol_mapping(db: Session) -> dict:
    """
    For every active NSE/EQ instrument in our DB, tries to find a
    matching Angel symboltoken using the "-EQ" suffix pattern, and
    stores it. Returns a summary including any UNMATCHED symbols so
    they can be reviewed manually rather than silently dropped from
    the screener later.
    """
    angel_map = fetch_angel_nse_equity_map()

    our_instruments = db.query(Instrument).filter_by(exchange="NSE", instrument_type="EQ", is_active=True).all()

    matched = 0
    unmatched = []

    for instrument in our_instruments:
        angel_symbol = f"{instrument.trading_symbol}-EQ"
        token = angel_map.get(angel_symbol)

        if token:
            instrument.angel_symbol_token = token
            matched += 1
        else:
            unmatched.append(instrument.trading_symbol)

    db.commit()

    return {
        "total_checked": len(our_instruments),
        "matched": matched,
        "unmatched_count": len(unmatched),
        "unmatched_symbols": unmatched,  # full list, so nothing is hidden
    }
