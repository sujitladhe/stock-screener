"""
scripts/test_ventura_websocket.py — a throwaway TEST script to see the
REAL shape of a live tick message from Ventura's WebSocket feed.

The docs only show a full example for "ltp_depth" mode (LTP + 5-level
market depth) — we actually want plain "ltp" mode (just price/volume,
no depth), and I don't have a confirmed example of what that message
looks like. Rather than guess field order and build the cumulative-
volume engine against a guess, this script subscribes to a couple of
well-known liquid stocks and just prints whatever comes back.

IMPORTANT: only run this DURING MARKET HOURS (9:15 AM - 3:30 PM IST,
weekdays) — outside market hours there's no trading, so no ticks will
arrive and you'll just see silence.

RUN:
    cd backend
    python -m scripts.test_ventura_websocket
"""

import asyncio
import json
import urllib.parse

import websockets

from app.database import SessionLocal
from app.config import settings
from app import ventura_client
from app.models import Instrument

WS_BASE_URL = "wss://easeapi-ws.venturasecurities.com/v1/easeapi_mktdata"

# Well-known, highly liquid stocks — good test candidates since they
# should tick frequently during market hours.
TEST_SYMBOLS = ["RELIANCE", "SBIN", "TCS"]


def get_test_tokens(db) -> dict:
    """Looks up exchange_token for our test symbols from our own DB."""
    instruments = (
        db.query(Instrument)
        .filter(Instrument.trading_symbol.in_(TEST_SYMBOLS), Instrument.exchange == "NSE")
        .all()
    )
    return {inst.trading_symbol: inst.exchange_token for inst in instruments}


async def listen(auth_token: str, tokens: dict, seconds: int = 30):
    query = urllib.parse.urlencode({
        "app_key": settings.ventura_service_app_key,
        "client_id": settings.ventura_service_client_id,
        "authorization": auth_token,
    })
    url = f"{WS_BASE_URL}?{query}"

    print(f"Connecting to {WS_BASE_URL} ...")
    async with websockets.connect(url) as ws:
        print("Connected. Subscribing to test tokens...")

        subscribe_msg = {
            "actions": ["nse:ltp"],
            "token": list(tokens.values()),
            "mode": "sub",
        }
        print(f"Sending: {json.dumps(subscribe_msg)}")
        await ws.send(json.dumps(subscribe_msg))

        print(f"\nListening for {seconds} seconds — printing every raw message received...\n")
        try:
            async with asyncio.timeout(seconds):
                async for message in ws:
                    print(f"RAW MESSAGE: {message}")
        except asyncio.TimeoutError:
            print(f"\nDone listening ({seconds}s elapsed).")


def main():
    db = SessionLocal()
    try:
        tokens = get_test_tokens(db)
        print(f"Test symbols and their exchange_token: {tokens}")
        if not tokens:
            print("Could not find test symbols in the instruments table — did sync_instruments run?")
            return

        print("Logging into Ventura (service account)...")
        token_data = ventura_client.login(
            app_key=settings.ventura_service_app_key,
            app_secret=settings.ventura_service_app_secret,
            client_id=settings.ventura_service_client_id,
            pin=settings.ventura_service_pin,
            totp_secret=settings.ventura_service_totp_secret,
        )
        auth_token = token_data["auth_token"]
        print("Login successful.")

        asyncio.run(listen(auth_token, tokens))
    finally:
        db.close()


if __name__ == "__main__":
    main()
