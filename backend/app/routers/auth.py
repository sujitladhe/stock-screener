"""
routers/auth.py — the web-facing login/logout endpoints.

Flow:
  POST /auth/login    — user submits Ventura credentials, session cookie set.
  POST /auth/logout   — deactivates session, clears cookie.
  GET  /auth/me       — returns client_id if logged in.
  POST /auth/refresh  — NEW: force-checks and refreshes the Ventura token.
                        Returns {"client_id": ..., "refreshed": bool} so the
                        frontend can tell the user whether re-login was needed
                        or the session was already active.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, Cookie
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import UserSession, now_ist_naive
from app.security import encrypt, generate_session_token
from app import ventura_client
from app.dependencies import get_current_session
from app.session_service import token_needs_refresh, ensure_fresh_token

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    app_key: str
    app_secret: str
    client_id: str
    pin: str
    totp_secret: str


@router.post("/login")
def login(req: LoginRequest, response: Response, db: Session = Depends(get_db)):
    try:
        token_data = ventura_client.login(
            app_key=req.app_key,
            app_secret=req.app_secret,
            client_id=req.client_id,
            pin=req.pin,
            totp_secret=req.totp_secret,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=401, detail="Login failed. Check your credentials and try again.") from e

    session_token = generate_session_token()

    session_row = UserSession(
        session_token=session_token,
        client_id=req.client_id,
        app_key=req.app_key,
        app_secret_encrypted=encrypt(req.app_secret),
        pin_encrypted=encrypt(req.pin),
        totp_secret_encrypted=encrypt(req.totp_secret),
        ventura_auth_token=token_data.get("auth_token"),
        ventura_auth_expiry=_parse_ventura_datetime(token_data.get("auth_expiry")),
        ventura_refresh_token=token_data.get("refresh_token"),
        ventura_refresh_expiry=_parse_ventura_datetime(token_data.get("refresh_expiry")),
        ventura_token_refreshed_date=now_ist_naive().date(),
    )
    db.add(session_row)
    db.commit()

    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )

    return {"client_id": req.client_id, "status": "logged_in"}


@router.post("/logout")
def logout(
    response: Response,
    db: Session = Depends(get_db),
    session_cookie: str | None = Cookie(default=None, alias="screener_session"),
):
    if session_cookie:
        session_row = db.query(UserSession).filter_by(session_token=session_cookie).first()
        if session_row:
            session_row.is_active = False
            db.commit()

    response.delete_cookie(settings.session_cookie_name)
    return {"status": "logged_out"}


@router.get("/me")
def me(session_row: UserSession = Depends(get_current_session)):
    return {"client_id": session_row.client_id}


@router.post("/refresh")
def refresh_session(
    db: Session = Depends(get_db),
    session_cookie: str | None = Cookie(default=None, alias="screener_session"),
):
    """
    Explicitly checks whether the stored Ventura auth token is still valid
    and refreshes it if not. Returns:
      {"client_id": ..., "refreshed": false}  — token was already active, no re-login needed
      {"client_id": ..., "refreshed": true}   — token was stale, re-login was performed
      HTTP 401                                 — re-login failed (user must log in manually)

    This endpoint is called by the "Refresh session" button in the topbar, giving the user
    an explicit way to recover from an expired Ventura token without a full logout+login.
    """
    if not session_cookie:
        raise HTTPException(status_code=401, detail="Not logged in.")

    session_row = (
        db.query(UserSession)
        .filter_by(session_token=session_cookie, is_active=True)
        .first()
    )
    if not session_row:
        raise HTTPException(status_code=401, detail="Session not found or logged out.")

    # Check BEFORE refreshing so we can report accurately to the frontend.
    was_stale = token_needs_refresh(session_row)

    if was_stale:
        try:
            ensure_fresh_token(db, session_row)
        except RuntimeError as e:
            # Re-login failed — mark session inactive so stale credentials don't linger.
            session_row.is_active = False
            db.commit()
            raise HTTPException(
                status_code=401,
                detail="Re-login failed. Please log in again.",
            ) from e

    session_row.last_active_at = datetime.utcnow()
    db.commit()

    return {
        "client_id": session_row.client_id,
        "refreshed": was_stale,
    }


def _parse_ventura_datetime(value: str | None):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
