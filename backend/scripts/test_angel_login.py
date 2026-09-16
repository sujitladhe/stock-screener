"""
scripts/test_angel_login.py — run this once to confirm the Angel One
login integration works end-to-end (reads credentials from .env,
logs in, stores the session, prints confirmation).

RUN:
    cd backend
    python -m scripts.test_angel_login
"""

from app.database import SessionLocal
from app.config import settings
from app import angel_client


def main():
    db = SessionLocal()
    try:
        print("Attempting Angel One login...")
        token = angel_client.get_valid_jwt_token(
            db,
            client_code=settings.angel_client_code,
            mpin=settings.angel_mpin,
            api_key=settings.angel_api_key,
            totp_secret=settings.angel_totp_secret,
        )
        print(f"Login successful. JWT token (first 20 chars): {token[:20]}...")

        print("\nRunning it again to confirm the stored token is reused (not a fresh login)...")
        token2 = angel_client.get_valid_jwt_token(
            db,
            client_code=settings.angel_client_code,
            mpin=settings.angel_mpin,
            api_key=settings.angel_api_key,
            totp_secret=settings.angel_totp_secret,
        )
        if token == token2:
            print("Confirmed: same token returned — reuse logic is working.")
        else:
            print("NOTE: got a different token second time — investigate before relying on reuse.")

    except Exception as e:
        print(f"FAILED: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
