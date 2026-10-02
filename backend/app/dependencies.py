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
first wins, and both funnel through the same relogin-or-fail path.

The actual refresh rules now live in app/session_service.py (unchanged,
just moved) so the auto-trade engine can apply the exact same rules
when it has to place an order with no browser request in flight.
"""

from datetime import datetime

from fastapi import Depends, HTTPException, Cookie
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import UserSession
from app.session_service import token_needs_refresh, ensure_fresh_token


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

    # If the Ventura auth_token has expired, OR hasn't been refreshed
    # yet today, relogin using the stored (encrypted) credentials
    # rather than forcing the user to log in again through the browser.
    #
    # NOTE: ideally this would use Ventura's refresh_token to get a new
    # auth_token without redoing TOTP — but we haven't confirmed that
    # endpoint/flow exists or how it works yet. For now we fall back to
    # a full relogin with the stored TOTP secret, which is slightly
    # heavier but works with what we've verified so far. Revisit once
    # we confirm the refresh-token exchange with Ventura support.
    if token_needs_refresh(session_row):
        try:
            ensure_fresh_token(db, session_row)
        except RuntimeError as e:
            session_row.is_active = False
            db.commit()
            raise HTTPException(
                status_code=401,
                detail="Your session expired and we couldn't automatically log you back in. Please log in again.",
            ) from e

    session_row.last_active_at = datetime.utcnow()
    db.commit()

    return session_row
