"""
routers/market_breadth.py — daily 50-day MA breadth endpoint.

GET /market-breadth?days=90

Returns per-trading-day counts of how many stocks are above vs. below their
50-day simple moving average, ordered newest first.

Only dates for which every stock already has at least 50 prior candles are
included — enforced by the ROW_NUMBER >= 50 guard inside the SQL.
"""

from datetime import date
from typing import List

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_session
from app.models import UserSession

router = APIRouter(prefix="/market-breadth", tags=["market_breadth"])


class BreadthRow(BaseModel):
    candle_date: date
    above_count: int
    below_count: int
    total_count: int
    breadth_pct: float


_SQL = text("""
    WITH ranked AS (
        SELECT
            instrument_id,
            candle_date,
            close,
            AVG(close) OVER (
                PARTITION BY instrument_id
                ORDER BY candle_date
                ROWS BETWEEN 49 PRECEDING AND CURRENT ROW
            ) AS ma50,
            ROW_NUMBER() OVER (
                PARTITION BY instrument_id
                ORDER BY candle_date
            ) AS day_num
        FROM daily_candles
    ),
    valid AS (
        SELECT instrument_id, candle_date, close, ma50
        FROM ranked
        WHERE day_num >= 50
    ),
    breadth AS (
        SELECT
            candle_date,
            COUNT(CASE WHEN close > ma50 THEN 1 END)  AS above_count,
            COUNT(CASE WHEN close <= ma50 THEN 1 END) AS below_count,
            COUNT(*)                                   AS total_count
        FROM valid
        GROUP BY candle_date
    )
    SELECT
        candle_date,
        above_count,
        below_count,
        total_count,
        ROUND(above_count * 100.0 / NULLIF(total_count, 0), 1) AS breadth_pct
    FROM breadth
    ORDER BY candle_date DESC
    LIMIT :days
""")


@router.get("", response_model=List[BreadthRow])
def get_market_breadth(
    days: int = Query(default=90, ge=1, le=365, description="Number of trading days to return"),
    db: Session = Depends(get_db),
    _: UserSession = Depends(get_current_session),
):
    rows = db.execute(_SQL, {"days": days}).fetchall()
    return [
        BreadthRow(
            candle_date=r.candle_date,
            above_count=int(r.above_count),
            below_count=int(r.below_count),
            total_count=int(r.total_count),
            breadth_pct=float(r.breadth_pct or 0),
        )
        for r in rows
    ]
