from sqlalchemy import (
    Column, Integer, String, Date, DateTime, Numeric,
    BigInteger, UniqueConstraint, Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime
from app.database import Base


class OptionInstrumentMaster(Base):
    __tablename__ = "option_instrument_master"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    token       = Column(String, nullable=False, unique=True, index=True)
    symbol      = Column(String, nullable=False)
    name        = Column(String, nullable=True)
    strike      = Column(Integer, nullable=False)
    expiry      = Column(Date, nullable=False)
    option_type = Column(String(2), nullable=False)   # "CE" or "PE"
    lot_size    = Column(Integer, nullable=False)
    fetched_at  = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_option_master_expiry_strike", "expiry", "strike", "option_type"),
    )


class OptionEodSnapshot(Base):
    __tablename__ = "option_eod_snapshot"

    id        = Column(Integer, primary_key=True, autoincrement=True)
    date      = Column(Date, nullable=False, index=True)
    expiry    = Column(Date, nullable=False)
    strike    = Column(Integer, nullable=False)
    ce_oi     = Column(BigInteger, nullable=True)
    pe_oi     = Column(BigInteger, nullable=True)
    ce_ltp    = Column(Numeric(12, 2), nullable=True)
    pe_ltp    = Column(Numeric(12, 2), nullable=True)
    ce_volume = Column(BigInteger, nullable=True)
    pe_volume = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("date", "expiry", "strike",
                         name="uq_option_eod_date_expiry_strike"),
    )


class OptionDailySummary(Base):
    __tablename__ = "option_daily_summary"

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    date                 = Column(Date, nullable=False)
    expiry               = Column(Date, nullable=False)
    spot_close           = Column(Numeric(10, 2), nullable=True)
    pcr                  = Column(Numeric(6, 3), nullable=True)
    max_pain             = Column(Integer, nullable=True)
    atm_iv               = Column(Numeric(6, 2), nullable=True)
    iv_skew              = Column(Numeric(6, 2), nullable=True)
    expected_move_range  = Column(Numeric(8, 2), nullable=True)
    created_at           = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("date", name="uq_option_daily_summary_date"),
    )


class OptionGuidanceLog(Base):
    __tablename__ = "option_guidance_log"

    id                       = Column(Integer, primary_key=True, autoincrement=True)
    logged_at                = Column(DateTime, nullable=False, index=True)
    expiry                   = Column(Date, nullable=True)
    spot                     = Column(Numeric(10, 2), nullable=True)
    score                    = Column(Integer, nullable=True)
    bias                     = Column(String(20), nullable=True)
    confidence               = Column(Integer, nullable=True)
    top_opportunity_strike   = Column(Integer, nullable=True)
    top_opportunity_type     = Column(String(20), nullable=True)
    signal_breakdown         = Column(JSONB, nullable=True)
    created_at               = Column(DateTime, default=datetime.utcnow)
