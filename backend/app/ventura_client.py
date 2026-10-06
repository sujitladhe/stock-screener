"""
ventura_client.py — talks to Ventura's EaseAPI. This is the same
logic as the original standalone auth.py, but refactored to accept
credentials as arguments (since each web app user supplies their own),
rather than reading them from a shared .env file.

fetch_circuit_pct() is a new addition (migration 0004) — uses the
Ventura OHLCV endpoint to get upper/lower circuit limits for a stock
and compute the circuit % band (typically 5, 10, or 20 on NSE).
The OHLCV endpoint is documented at:
  https://easeapi.venturasecurities.com/docs/ease-api/v1/market_quotes/
Response array layout (per docs):
  [token, ltp, open, high, low, close, volume, timestamp, upper_circuit, lower_circuit]
"""

import hashlib
import uuid
from typing import Optional

import pyotp
import requests

LOGIN_URL = "https://easeapi.venturasecurities.com/login/v1/authorization/totp"
OHLCV_URL = "https://easeapi.venturasecurities.com/instrument/v1/ohlcv"


def get_server_mac_address() -> str:
    mac_int = uuid.getnode()
    mac_hex = f"{mac_int:012x}"
    return ":".join(mac_hex[i:i + 2] for i in range(0, 12, 2))


def compute_data_hash(app_key: str, app_secret: str) -> str:
    raw = f"{app_key}{app_secret}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest().lower()


def generate_totp_code(totp_secret: str) -> str:
    return pyotp.TOTP(totp_secret).now()


def login(
    app_key: str,
    app_secret: str,
    client_id: str,
    pin: str,
    totp_secret: str,
    mac_address: str | None = None,
) -> dict:
    """
    Logs into Ventura EaseAPI for one user's credentials.
    Returns the parsed JSON response (client_id, auth_token,
    auth_expiry, refresh_token, refresh_expiry) on success.
    Raises RuntimeError with a clear message on failure.
    """
    headers = {
        "x-app-key": app_key,
        "x-client-id": client_id,
        "x-mac-address": mac_address or get_server_mac_address(),
        "Content-Type": "application/json",
    }

    payload = {
        "password": pin,
        "data": compute_data_hash(app_key, app_secret),
        "totp": generate_totp_code(totp_secret),
    }

    response = requests.post(LOGIN_URL, headers=headers, json=payload, timeout=15)

    if response.status_code != 200:
        raise RuntimeError(
            f"Ventura login failed (status {response.status_code}): {response.text}"
        )

    data = response.json()
    if "auth_token" not in data:
        raise RuntimeError(f"Ventura login response missing auth_token: {data}")

    return data


def fetch_circuit_pct(
    exchange_token: str,
    prev_close: float,
    app_key: str,
    client_id: str,
    auth_token: str,
) -> Optional[int]:
    """
    Fetches OHLCV data for one exchange_token from Ventura's market-quotes
    endpoint and returns the upper-circuit band as an integer percentage
    (e.g. 5, 10, or 20) — the commonly used NSE circuit categories.

    Calculation:
        circuit_pct = round((upper_circuit_limit - prev_close) / prev_close * 100)

    prev_close here is the previous day's close price, sourced from the live
    tick feed (tick field index 6 / StockState.prev_close) — NOT the "close"
    returned by OHLCV, which is today's closing LTP so far.

    Returns None if the API call fails, data is unavailable, or prev_close is
    invalid.  Best-effort only — a None result means the Circuit column shows
    "–" in the UI; it never stops an alert from being saved or broadcast.

    Uses the service-account credentials (same login used for the WS feed),
    so this must only be called from the ws_client background engine.
    """
    if not prev_close or prev_close <= 0:
        return None

    headers = {
        "x-client-id": client_id,
        "x-app-key": app_key,
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
    }
    payload = {"exchange": "NSE", "tokens": [exchange_token]}

    try:
        response = requests.post(OHLCV_URL, headers=headers, json=payload, timeout=5)
        if response.status_code != 200:
            return None

        body = response.json()
        if not body.get("success") or not body.get("data"):
            return None

        row = body["data"][0]
        # Row layout per docs: [token, ltp, open, high, low, close, volume, ts,
        #                        upper_circuit, lower_circuit]
        if len(row) < 9:
            return None

        upper_circuit = row[8]
        if not upper_circuit or upper_circuit <= 0:
            return None

        pct = round((upper_circuit - prev_close) / prev_close * 100)
        return pct if pct > 0 else None

    except Exception:
        return None
