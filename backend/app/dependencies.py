"""
dependencies.py — shared FastAPI dependencies. The important one is
get_current_session, which every protected route (screener, watchlist,
orders, etc.) will use to identify who's making the request and make
sure their Ventura auth_token is still valid — silently refreshing it
behind the scenes if it expired, so the user's browser session stays
alive without them noticing (matches requirement 1b: "sessions should
be maintained until users do not log out manually").

DAY-BOUNDARY RELOGIN (added after a real failure): a real order
placement failed with "login token expired" even though the browser
session itself was a week old and, per our own auth_expiry check,
should have been silently refreshed already. Ventura's docs don't
explicitly state whether an auth_token obtained on one trading day is
expected to still work on a later one, so rather than trust
auth_expiry alone, this now ALSO forces a fresh login whenever the
token wasn't refreshed on today's IST date -- whichever check fires
first wins, and both funnel through the same relogin-or-fail path
below.
"""

from datetime import datetime

from fastapi import Depends, HTTPException, Cookie
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import UserSession, now_ist_naive
from app.security import decrypt
from app.config import settings
from app import ventura_client


def get_current_session(
    db: Session = Depends(get_db),
    session_cookie: str | None = Cookie(default=None, alias="screener_session"),
) -> UserSession:
    if not session_cookie:
        raise HTTPException(status_code=401, detail="Not logged in.")

    session_row = (
        db.query(UserSession)
        .filter_by(session_token=session_cookie, is_active=True)
        .first()
    )
    if not session_row:
        raise HTTPException(status_code=401, detail="Session not found or logged out.")

    today_ist = now_ist_naive().date()
    is_expired = not session_row.ventura_auth_expiry or datetime.utcnow() >= session_row.ventura_auth_expiry
    is_stale_for_today = session_row.ventura_token_refreshed_date != today_ist

    # If the Ventura auth_token has expired, OR hasn't been refreshed
    # yet today (see module docstring), relogin using the stored
    # (encrypted) credentials rather than forcing the user to log in
    # again through the browser.
    #
    # NOTE: ideally this would use Ventura's refresh_token to get a new
    # auth_token without redoing TOTP — but we haven't confirmed that
    # endpoint/flow exists or how it works yet. For now we fall back to
    # a full relogin with the stored TOTP secret, which is slightly
    # heavier but works with what we've verified so far. Revisit once
    # we confirm the refresh-token exchange with Ventura support.
    if is_expired or is_stale_for_today:
        try:
            token_data = ventura_client.login(
                app_key=session_row.app_key,
                app_secret=decrypt(session_row.app_secret_encrypted),
                client_id=session_row.client_id,
                pin=decrypt(session_row.pin_encrypted),
                totp_secret=decrypt(session_row.totp_secret_encrypted),
            )
        except RuntimeError as e:
            session_row.is_active = False
            db.commit()
            raise HTTPException(
                status_code=401,
                detail="Your session expired and we couldn't automatically log you back in. Please log in again.",
            ) from e

        session_row.ventura_auth_token = token_data.get("auth_token")
        session_row.ventura_auth_expiry = datetime.strptime(
            token_data["auth_expiry"], "%Y-%m-%d %H:%M:%S"
        )
        session_row.ventura_refresh_token = token_data.get("refresh_token")
        session_row.ventura_token_refreshed_date = today_ist
        db.commit()

    session_row.last_active_at = datetime.utcnow()
    db.commit()

    return session_row
