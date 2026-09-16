"""
ventura_client.py — talks to Ventura's EaseAPI. This is the same
logic as the original standalone auth.py, but refactored to accept
credentials as arguments (since each web app user supplies their own),
rather than reading them from a shared .env file.
"""

import hashlib
import uuid

import pyotp
import requests

LOGIN_URL = "https://easeapi.venturasecurities.com/login/v1/authorization/totp"


def get_server_mac_address() -> str:
    """
    NOTE / ASSUMPTION TO VERIFY: unlike the single-user script, we
    don't have a separate MAC address per friend using this app —
    everyone connects through this one server. Using this server's MAC
    for every login attempt is an assumption; confirm with Ventura
    support whether the MAC address needs to match something
    registered per app_key/client_id, or if any consistent MAC is fine
    as long as it doesn't change between requests for the same user.
    """
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
