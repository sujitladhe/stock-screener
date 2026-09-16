# Screener App — Backend, Step 1: Login System

This replaces the old standalone `auth.py` approach with a proper
multi-user web login: each user (you + friends) submits their own
Ventura credentials through an API call, gets a session cookie, and
stays logged in until they manually log out (the backend auto-refreshes
their Ventura token behind the scenes).

## Setup

1. Make sure Postgres is running on your VM. Create a database and user:
   ```sql
   CREATE DATABASE screener_db;
   CREATE USER screener_user WITH PASSWORD 'yourpassword';
   GRANT ALL PRIVILEGES ON DATABASE screener_db TO screener_user;
   ```

2. Install dependencies:
   ```
   cd backend
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and fill in:
   - `DATABASE_URL` — e.g. `postgresql://screener_user:yourpassword@localhost:5432/screener_db`
   - `ENCRYPTION_KEY` — generate with:
     ```
     python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
     ```

4. Run the server:
   ```
   uvicorn app.main:app --reload --port 8000
   ```
   On first run, it will automatically create the `user_sessions` table
   in your Postgres database.

## Testing without a frontend yet

You can test the login flow directly with `curl` before we build the
React UI:

```bash
curl -i -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -c cookies.txt \
  -d '{
    "app_key": "YOUR_APP_KEY",
    "app_secret": "YOUR_APP_SECRET",
    "client_id": "YOUR_CLIENT_ID",
    "pin": "YOUR_PIN",
    "totp_secret": "YOUR_TOTP_SECRET"
  }'
```

The `-c cookies.txt` saves the session cookie. If login succeeds you'll
see `{"client_id": "...", "status": "logged_in"}`.

Then test that the session persists:
```bash
curl -i http://localhost:8000/auth/me -b cookies.txt
```
Should return `{"client_id": "..."}`.

And test logout:
```bash
curl -i -X POST http://localhost:8000/auth/logout -b cookies.txt
curl -i http://localhost:8000/auth/me -b cookies.txt   # should now fail with 401
```

## Known gaps / things to revisit (flagging honestly, not hiding these)

- **MAC address**: `ventura_client.py` currently uses the server's own
  MAC address for every login, regardless of which friend is logging
  in. This is an assumption — worth confirming with Ventura support
  whether this is fine for a multi-user setup, or whether each
  app_key needs a specific registered MAC.
- **Token refresh**: when a session's Ventura auth_token expires, we
  currently do a full relogin (PIN + fresh TOTP) rather than using
  Ventura's `refresh_token` — because we haven't confirmed the
  refresh-token exchange endpoint exists or how it works. Worth asking
  Ventura support about this; it would be a lighter-weight refresh.
- **Error logging**: login failures currently just return a generic
  "Login failed" message to the browser without logging the real
  Ventura error anywhere server-side. Fine for now while testing
  yourself, but before your friends start using this, we should add
  real server-side logging so you can actually debug their login
  issues.
- **HTTPS**: `COOKIE_SECURE=false` is only safe for local testing.
  Before any friend logs in with real credentials over the internet,
  this needs to run behind HTTPS with `COOKIE_SECURE=true` — otherwise
  session cookies (and the login request itself) travel in plaintext.
