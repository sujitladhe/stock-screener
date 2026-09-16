"""
angel_client.py — logs into Angel One SmartAPI using loginByPassword
(confirmed working against a real account — loginByMPIN was tried and
rejected, so we use loginByPassword with the MPIN passed in the
"password" field, per Angel One's actual behavior for this account).

This is a SHARED service-account login (one set of Angel One
credentials in .env, used only for pulling historical data) — not
tied to any individual app user. Only Ventura handles per-user
login/trading in this app.

Angel One's response has no expiry field, so rather than guessing when
a token goes stale, get_valid_jwt_token() hands out the last known
token, and callers should use request_with_retry() (below) so a stale
token gets one automatic relogin-and-retry instead of just failing.
"""

import socket
import subprocess
from datetime import datetime

import pyotp
import requests
from sqlalchemy.orm import Session

from app.models import AngelSession

LOGIN_URL = "https://apiconnect.angelone.in/rest/auth/angelbroking/user/v1/loginByPassword"


def get_local_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return socket.gethostbyname(socket.gethostname())


def get_public_ip() -> str:
    try:
        result = subprocess.run(
            ["curl", "-4", "-fsS", "--max-time", "10", "https://checkip.amazonaws.com"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except Exception as exc:
        raise RuntimeError(f"Could not determine public IP: {exc}") from exc


def get_mac_address() -> str:
    try:
        route = subprocess.run(
            ["ip", "route", "get", "1.1.1.1"], capture_output=True, text=True, check=True,
        )
        parts = route.stdout.split()
        interface = parts[parts.index("dev") + 1] if "dev" in parts else None
        if not interface:
            return ""
        link = subprocess.run(
            ["ip", "link", "show", interface], capture_output=True, text=True, check=True,
        )
        for line in link.stdout.splitlines():
            if "link/ether" in line:
                return line.split()[1]
    except Exception:
        pass
    return ""


def login(client_code: str, mpin: str, api_key: str, totp_secret: str) -> dict:
    """
    Logs into Angel One. Returns dict with jwt_token, refresh_token,
    feed_token. Raises RuntimeError with a clear message on failure.
    """
    local_ip = get_local_ip()
    public_ip = get_public_ip()
    mac_address = get_mac_address()

    if not public_ip or not mac_address:
        raise RuntimeError(
            f"Could not determine network details needed for login "
            f"(public_ip={public_ip!r}, mac_address={mac_address!r})."
        )

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-UserType": "USER",
        "X-SourceID": "WEB",
        "X-ClientLocalIP": local_ip,
        "X-ClientPublicIP": public_ip,
        "X-MACAddress": mac_address,
        "X-PrivateKey": api_key,
    }

    payload = {
        "clientcode": client_code,
        "password": mpin,  # confirmed: Angel expects the MPIN in the "password" field for this account
        "totp": pyotp.TOTP(totp_secret).now(),
    }

    response = requests.post(LOGIN_URL, headers=headers, json=payload, timeout=30)

    if response.status_code != 200:
        raise RuntimeError(f"Angel One login failed (status {response.status_code}): {response.text}")

    data = response.json()

    if not data.get("status"):
        raise RuntimeError(
            f"Angel One login rejected: {data.get('message')} (errorcode: {data.get('errorcode')})"
        )

    token_data = data["data"]
    return {
        "jwt_token": token_data.get("jwtToken"),
        "refresh_token": token_data.get("refreshToken"),
        "feed_token": token_data.get("feedToken"),
    }


def _login_and_store(db: Session, client_code: str, mpin: str, api_key: str, totp_secret: str) -> AngelSession:
    token_data = login(client_code, mpin, api_key, totp_secret)

    session_row = db.query(AngelSession).first()
    if not session_row:
        session_row = AngelSession()
        db.add(session_row)

    session_row.jwt_token = token_data["jwt_token"]
    session_row.refresh_token = token_data["refresh_token"]
    session_row.feed_token = token_data["feed_token"]
    session_row.logged_in_at = datetime.utcnow()
    db.commit()
    db.refresh(session_row)
    return session_row


def get_valid_jwt_token(db: Session, client_code: str, mpin: str, api_key: str, totp_secret: str) -> str:
    """
    Returns a usable JWT token — reuses the last stored one if it
    exists, otherwise logs in fresh. Does NOT guarantee the token is
    still accepted by Angel One (we have no expiry to check against) —
    use request_with_retry() for actual API calls so an unauthorized
    response triggers one automatic relogin.
    """
    session_row = db.query(AngelSession).first()
    if session_row and session_row.jwt_token:
        return session_row.jwt_token

    session_row = _login_and_store(db, client_code, mpin, api_key, totp_secret)
    return session_row.jwt_token


def request_with_retry(
    db: Session,
    client_code: str,
    mpin: str,
    api_key: str,
    totp_secret: str,
    method: str,
    url: str,
    **kwargs,
) -> requests.Response:
    """
    Makes an authenticated Angel One API request, automatically
    relogging in and retrying ONCE if the first attempt fails due to
    an expired/invalid token. This exists specifically because Angel
    One's login response gives us no expiry to check proactively.
    """
    jwt_token = get_valid_jwt_token(db, client_code, mpin, api_key, totp_secret)

    def _build_headers(token: str) -> dict:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-ClientLocalIP": get_local_ip(),
            "X-ClientPublicIP": get_public_ip(),
            "X-MACAddress": get_mac_address(),
            "X-PrivateKey": api_key,
            "Authorization": f"Bearer {token}",
        }

    response = requests.request(method, url, headers=_build_headers(jwt_token), timeout=30, **kwargs)

    # IMPORTANT distinction: a 403 can mean two very different things
    # from Angel One, confirmed by a real failure we hit — "exceeding
    # access rate" (rate limiting, nothing to do with the token) vs an
    # actually invalid/expired token. Relogging in does nothing to fix
    # rate limiting and wastes an extra API call, so we must NOT treat
    # a rate-limit 403 as an auth failure.
    response_text_lower = response.text.lower()
    is_rate_limited = response.status_code == 403 and "exceeding access rate" in response_text_lower

    looks_unauthorized = False
    if response.status_code == 401:
        looks_unauthorized = True
    elif response.status_code == 403 and not is_rate_limited:
        looks_unauthorized = True
    elif response.status_code == 200:
        try:
            body = response.json()
            if body.get("errorcode") in ("AG8001", "AG8002") or "invalid token" in str(body.get("message", "")).lower():
                looks_unauthorized = True
        except ValueError:
            pass

    if looks_unauthorized:
        session_row = _login_and_store(db, client_code, mpin, api_key, totp_secret)
        response = requests.request(
            method, url, headers=_build_headers(session_row.jwt_token), timeout=30, **kwargs
        )

    return response
