"""
main.py — FastAPI app entry point.

Updated in 0004: includes the ignored router (per-user daily ignore list).
"""

import asyncio
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routers import auth, screener, watchlist, instruments, orders, alerts, positions
from app.routers import ignored  # NEW (0004)
from app.ws_manager import manager
from app import ws_client
from app import engine_scheduler
from app.config import settings

app = FastAPI(title="Screener App")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(screener.router)
app.include_router(ignored.router)   # NEW (0004) — /screener/ignored/*
app.include_router(watchlist.router)
app.include_router(instruments.router)
app.include_router(orders.router)
app.include_router(alerts.router)
app.include_router(positions.router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
async def start_live_engine():
    if not settings.auto_start_live_engine:
        print("Live engine NOT started (AUTO_START_LIVE_ENGINE=false in .env).")
        return

    if settings.engine_scheduler_enabled:
        print("Engine scheduler ENABLED — the live engine will run only inside the market window.")
        coro = engine_scheduler.run_engine_on_schedule(
            on_alert=manager.broadcast,
            on_user_alert=manager.send_to_client,
        )
    else:
        coro = ws_client.run_engine(
            on_alert=manager.broadcast,
            on_user_alert=manager.send_to_client,
        )

    app.state.engine_task = asyncio.create_task(coro)


@app.get("/health")
def health():
    return {"status": "ok"}


_frontend_dist = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
if os.path.isdir(_frontend_dist):
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
else:
    print(f"NOTE: frontend build not found at {_frontend_dist} — "
          f"run 'npm run build' in frontend/ to serve it from this server.")
