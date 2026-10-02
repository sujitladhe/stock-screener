"""
session_service.py — keeps a user's stored Ventura auth_token fresh.

This logic used to live inline inside dependencies.get_current_session,
which only ever runs while a browser request is being served. Auto
trade (requirement 10) needs the SAME guarantee with NO browser
involved: at 9:15 AM the engine may have to place an order for a user
whose browser is closed, using that user's OWN Ventura session (hard
rule #10 in the handoff — never the shared service account). So the
refresh rules were pulled out here, unchanged, and both callers use
them:

  - dependencies.get_current_session (HTTP requests)
  - auto_trade_service (background order placement)

The two refresh conditions are exactly the ones already in production:
  1. ventura_auth_expiry has passed (or was never recorded), OR
  2. the token wasn't (re)obtained on today's IST date (handoff
     Section 3, #11 — Ventura's docs don't confirm cross-day validity,
     so we don't assume it).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import UserSession, now_ist_naive
from app.security import decrypt
from app import ventura_client


def token_needs_refresh(session_row: UserSession) -> bool:
    today_ist = now_ist_naive().date()
    is_expired = (
        not session_row.ventura_auth_expiry
        or datetime.utcnow() >= session_row.ventura_auth_expiry
    )
    is_stale_for_today = session_row.ventura_token_refreshed_date != today_ist
    return is_expired or is_stale_for_today


def refresh_session_token(db: Session, session_row: UserSession) -> None:
    """
    Logs into Ventura again with the stored (encrypted) credentials and
    saves the new token. Raises whatever ventura_client.login raises
    (RuntimeError for a Ventura-side failure).

    NOTE (unchanged from before): this is a full relogin with a fresh
    TOTP, not Ventura's refresh_token exchange, because that flow still
    hasn't been confirmed with Ventura support.
    """
    token_data = ventura_client.login(
        app_key=session_row.app_key,
        app_secret=decrypt(session_row.app_secret_encrypted),
        client_id=session_row.client_id,
        pin=decrypt(session_row.pin_encrypted),
        totp_secret=decrypt(session_row.totp_secret_encrypted),
    )

    session_row.ventura_auth_token = token_data.get("auth_token")
    session_row.ventura_auth_expiry = datetime.strptime(
        token_data["auth_expiry"], "%Y-%m-%d %H:%M:%S"
    )
    session_row.ventura_refresh_token = token_data.get("refresh_token")
    session_row.ventura_token_refreshed_date = now_ist_naive().date()
    db.commit()


def ensure_fresh_token(db: Session, session_row: UserSession) -> UserSession:
    """
    Refreshes the token if (and only if) it needs it, then returns the
    same row. Raises if the relogin fails.

    One extra safety net: if the relogin fails, we re-read the row
    before giving up. Two callers can race to refresh the same session
    (e.g. a browser request and the auto-trade engine at market open),
    and Ventura may reject a TOTP code that was just used — in that
    case the OTHER caller has already stored a good token, and we
    should simply use it instead of reporting a failure.
    """
    if not token_needs_refresh(session_row):
        return session_row

    try:
        refresh_session_token(db, session_row)
    except Exception:
        db.rollback()
        db.refresh(session_row)
        if not token_needs_refresh(session_row):
            return session_row
        raise

    return session_row


def get_latest_active_session(db: Session, client_id: str) -> Optional[UserSession]:
    """
    The most recently used, still-logged-in session for a client_id, or
    None if that user has logged out everywhere. Used by background
    jobs, which have no browser cookie to identify the session by.
    """
    return (
        db.query(UserSession)
        .filter_by(client_id=client_id, is_active=True)
        .order_by(UserSession.last_active_at.desc())
        .first()
    )
