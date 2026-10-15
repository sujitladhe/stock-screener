"""
routers/screener_settings.py — read and update the shared screener conditions.

GET /screener/settings  — returns current conditions (creates defaults if none).
PUT /screener/settings  — updates conditions; the live engine picks them up
                          within ~2 minutes via its periodic refresh.

These conditions are SHARED across all users — changing them affects what
every user sees on the Live screener.
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_session
from app.models import UserSession, ScreenerSettings

router = APIRouter(prefix="/screener/settings", tags=["screener"])

# Defaults that match the original hardcoded values in live_engine.py
_DEFAULTS = dict(
    cond1_multiplier=20,
    cond1_min_value_cr=4.0,
    cond2_multiplier=10,
    cond2_min_value_cr=6.0,
)


def _get_or_create(db: Session) -> ScreenerSettings:
    row = db.query(ScreenerSettings).first()
    if not row:
        row = ScreenerSettings(**_DEFAULTS)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _serialize(row: ScreenerSettings) -> dict:
    return {
        "cond1_multiplier": int(row.cond1_multiplier),
        "cond1_min_value_cr": float(row.cond1_min_value_cr),
        "cond2_multiplier": int(row.cond2_multiplier),
        "cond2_min_value_cr": float(row.cond2_min_value_cr),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


class UpdateScreenerSettingsRequest(BaseModel):
    cond1_multiplier: int
    cond1_min_value_cr: float
    cond2_multiplier: int
    cond2_min_value_cr: float


@router.get("")
def get_screener_settings(
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    return _serialize(_get_or_create(db))


@router.put("")
def update_screener_settings(
    req: UpdateScreenerSettingsRequest,
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    if req.cond1_multiplier <= 0 or req.cond2_multiplier <= 0:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Multipliers must be greater than 0.")
    if req.cond1_min_value_cr <= 0 or req.cond2_min_value_cr <= 0:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Minimum value must be greater than 0.")

    row = _get_or_create(db)
    row.cond1_multiplier = req.cond1_multiplier
    row.cond1_min_value_cr = req.cond1_min_value_cr
    row.cond2_multiplier = req.cond2_multiplier
    row.cond2_min_value_cr = req.cond2_min_value_cr
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _serialize(row)
