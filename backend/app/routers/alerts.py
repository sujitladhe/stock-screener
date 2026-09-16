"""
routers/alerts.py — user-defined alert management (requirement 9).

Creating/deleting an alert here also needs to update the LIVE, in-
memory alert-checking registry the running engine uses (see
app.alert_registry) -- otherwise a newly created alert wouldn't be
picked up until the whole server restarts, and a deleted one would
keep firing. That registry is a module-level dict shared between this
router and ws_client.py's tick loop, safe to mutate directly since
everything runs on one asyncio event loop (no multi-threading here).
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_session
from app.models import UserSession, Alert, AlertHistoryEntry, Instrument
from app import alert_registry

router = APIRouter(prefix="/alerts", tags=["alerts"])

VALID_METRICS = {"price", "value"}
VALID_OPERATORS = {"above", "below"}
VALID_COMBINATORS = {"AND", "OR"}


class CreateAlertRequest(BaseModel):
    trading_symbol: str
    condition_1_metric: str
    condition_1_operator: str
    condition_1_threshold: float
    condition_2_metric: Optional[str] = None
    condition_2_operator: Optional[str] = None
    condition_2_threshold: Optional[float] = None
    combinator: Optional[str] = None
    sound_enabled: bool = True


def _validate_conditions(req: CreateAlertRequest):
    if req.condition_1_metric not in VALID_METRICS:
        raise HTTPException(status_code=400, detail=f"condition_1_metric must be one of {VALID_METRICS}")
    if req.condition_1_operator not in VALID_OPERATORS:
        raise HTTPException(status_code=400, detail=f"condition_1_operator must be one of {VALID_OPERATORS}")

    has_condition_2 = req.condition_2_metric is not None
    if has_condition_2:
        if req.condition_2_metric not in VALID_METRICS:
            raise HTTPException(status_code=400, detail=f"condition_2_metric must be one of {VALID_METRICS}")
        if req.condition_2_operator not in VALID_OPERATORS:
            raise HTTPException(status_code=400, detail=f"condition_2_operator must be one of {VALID_OPERATORS}")
        if req.condition_2_threshold is None:
            raise HTTPException(status_code=400, detail="condition_2_threshold is required when condition_2_metric is set")
        if req.combinator not in VALID_COMBINATORS:
            raise HTTPException(status_code=400, detail=f"combinator must be one of {VALID_COMBINATORS} when condition_2 is set")


def _serialize_alert(a: Alert) -> dict:
    return {
        "id": a.id,
        "trading_symbol": a.trading_symbol,
        "condition_1_metric": a.condition_1_metric,
        "condition_1_operator": a.condition_1_operator,
        "condition_1_threshold": float(a.condition_1_threshold),
        "condition_2_metric": a.condition_2_metric,
        "condition_2_operator": a.condition_2_operator,
        "condition_2_threshold": float(a.condition_2_threshold) if a.condition_2_threshold is not None else None,
        "combinator": a.combinator,
        "sound_enabled": a.sound_enabled,
        "is_active": a.is_active,
        "created_at": a.created_at.isoformat(),
    }


@router.get("")
def list_alerts(db: Session = Depends(get_db), session: UserSession = Depends(get_current_session)):
    alerts = db.query(Alert).filter_by(client_id=session.client_id).order_by(Alert.created_at.desc()).all()
    return [_serialize_alert(a) for a in alerts]


@router.post("")
def create_alert(
    req: CreateAlertRequest,
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    _validate_conditions(req)

    instrument = (
        db.query(Instrument)
        .filter_by(trading_symbol=req.trading_symbol, exchange="NSE", instrument_type="EQ", is_active=True)
        .first()
    )
    if not instrument:
        raise HTTPException(status_code=404, detail=f"Unknown or inactive symbol: {req.trading_symbol}")

    alert = Alert(
        client_id=session.client_id,
        instrument_id=instrument.id,
        trading_symbol=instrument.trading_symbol,
        condition_1_metric=req.condition_1_metric,
        condition_1_operator=req.condition_1_operator,
        condition_1_threshold=req.condition_1_threshold,
        condition_2_metric=req.condition_2_metric,
        condition_2_operator=req.condition_2_operator,
        condition_2_threshold=req.condition_2_threshold,
        combinator=req.combinator,
        sound_enabled=req.sound_enabled,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)

    alert_registry.add_alert(alert)

    return _serialize_alert(alert)


# IMPORTANT: these two /history routes MUST be registered BEFORE
# /{alert_id} and /{alert_id}/toggle below. FastAPI/Starlette matches
# routes in registration order, not by specificity — a request to
# DELETE /alerts/history was previously matching DELETE /{alert_id}
# first (since "history" is a syntactically valid, if semantically
# wrong, value for a path parameter), causing a 422 instead of ever
# reaching this handler. This was a real bug, not a guess — confirmed
# by re-reading the route registration order.
@router.get("/history")
def get_history(db: Session = Depends(get_db), session: UserSession = Depends(get_current_session)):
    entries = (
        db.query(AlertHistoryEntry)
        .filter_by(client_id=session.client_id)
        .order_by(AlertHistoryEntry.triggered_at.desc())
        .all()
    )
    return [
        {
            "id": e.id,
            "trading_symbol": e.trading_symbol,
            "triggered_at": e.triggered_at.isoformat(),
            "price_at_trigger": float(e.price_at_trigger),
            "value_at_trigger": float(e.value_at_trigger),
            "condition_summary": e.condition_summary,
        }
        for e in entries
    ]


@router.delete("/history")
def clear_history(db: Session = Depends(get_db), session: UserSession = Depends(get_current_session)):
    db.query(AlertHistoryEntry).filter_by(client_id=session.client_id).delete()
    db.commit()
    return {"status": "cleared"}


@router.patch("/{alert_id}/toggle")
def toggle_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    alert = db.query(Alert).filter_by(id=alert_id, client_id=session.client_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found.")

    alert.is_active = not alert.is_active
    db.commit()

    if alert.is_active:
        alert_registry.add_alert(alert)
    else:
        alert_registry.remove_alert(alert.id)

    return _serialize_alert(alert)


@router.delete("/{alert_id}")
def delete_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    alert = db.query(Alert).filter_by(id=alert_id, client_id=session.client_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found.")

    db.delete(alert)
    db.commit()

    alert_registry.remove_alert(alert_id)

    return {"status": "deleted"}
