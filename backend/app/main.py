"""
main.py — FastAPI app entry point.

Run locally with:
    uvicorn app.main:app --reload --port 8000

IMPORTANT: the live tick engine now runs as a background task INSIDE
this same process (started on startup, see below) — not as the
separate scripts/run_live_engine.py process we used for earlier
testing. Running that standalone script AT THE SAME TIME as this app
would create two competing subscriptions to Ventura's feed and two
sets of alerts — don't run both at once against the same market
session.
"""

import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routers import auth, screener, watchlist, instruments, orders, alerts
from app.ws_manager import manager
from app import ws_client
from app.config import settings

# Schema management is now handled by Alembic (see alembic/ folder),
# not a create_all() call — removed so there's exactly one way tables
# get created or changed, tracked in migration history.

app = FastAPI(title="Screener App")

# Allows the React frontend to call this API and have cookies work
# correctly. Origins come from settings.allowed_origins (.env) rather
# than a hardcoded "localhost" — a real bug was caused by exactly this
# hardcoding: accessing the dev server via the EC2 box's public IP
# instead of "localhost" caused the browser to silently block every
# request, which surfaced as the app being stuck on a "Loading..."
# screen with no visible error.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(screener.router)
app.include_router(watchlist.router)
app.include_router(instruments.router)
app.include_router(orders.router)
app.include_router(alerts.router)

# Serves the basic test UI at http://your-server:8000/static/index.html
# — plain HTML/JS, no build step, used to prove the REST+WebSocket
# pipeline works before investing in the real React app.
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
async def start_live_engine():
    """
    Launches the live tick engine as a background task in the same
    asyncio event loop FastAPI/uvicorn already runs on — so it can run
    continuously alongside serving API requests, and can broadcast
    alerts to connected browsers the instant they happen via
    manager.broadcast.

    Controlled by settings.auto_start_live_engine — set this to false
    in .env while iterating on API/UI code with --reload, so every
    restart doesn't reconnect to Ventura and resubscribe to all
    ~2,655 stocks.
    """
    if settings.auto_start_live_engine:
        asyncio.create_task(ws_client.run_engine(
            on_alert=manager.broadcast,
            on_user_alert=manager.send_to_client,
        ))
    else:
        print("Live engine NOT started (AUTO_START_LIVE_ENGINE=false in .env).")


@app.get("/health")
def health():
    return {"status": "ok"}


# Serves the production-built React app (frontend/dist, created via
# `npm run build`) at the root path — this MUST be the last route
# registered, since Starlette matches routes in registration order and
# a mount at "/" would otherwise shadow every API route defined above
# it. Consolidating to one server (instead of a separate `npm run dev`
# process) means only ONE process needs to be started/stopped on a
# schedule, and avoids running Vite's dev server unattended in
# production, which it isn't designed for.
#
# If frontend/dist doesn't exist yet (e.g. fresh clone, dev-only
# setup), skip mounting rather than crash the whole app on startup.
import os

_frontend_dist = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
if os.path.isdir(_frontend_dist):
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
else:
    print(f"NOTE: frontend build not found at {_frontend_dist} — "
          f"run 'npm run build' in frontend/ to serve it from this server. "
          f"API endpoints still work without it.")
