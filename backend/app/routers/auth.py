"""
routers/auth.py — the web-facing login/logout endpoints.

Flow:
  POST /auth/login   — user submits app_key, app_secret, client_id,
                        pin, totp_secret. We log into Ventura, store
                        the encrypted credentials + tokens in a new
                        session row, and set a secure cookie.
  POST /auth/logout  — deactivates the session, clears the cookie.
  GET  /auth/me      — returns the current session's client_id if
                        logged in, used by the frontend to check
                        login state on page load.
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
        # Don't leak Ventura's raw error details to the browser —
        # log server-side (left as a TODO: wire up real logging) and
        # give the user a plain message.
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
        # Keeps a fresh login consistent with get_current_session's
        # day-boundary check — without this, a session created late at
        # night could otherwise be treated as "stale for today" on its
        # very first real request.
        ventura_token_refreshed_date=now_ist_naive().date(),
    )
    db.add(session_row)
    db.commit()

    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_token,
        httponly=True,          # JS on the page can't read this — reduces XSS risk
        secure=settings.cookie_secure,  # set true once you're on HTTPS
        samesite="lax",
        max_age=60 * 60 * 24 * 30,  # cookie itself lasts 30 days; see get_current_session
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
    """
    Used by the frontend on page load to check "is someone logged in,
    and who" — e.g. to decide whether to show the login page or the
    screener dashboard.
    """
    return {"client_id": session_row.client_id}


def _parse_ventura_datetime(value: str | None):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
