"""
database.py — sets up the SQLAlchemy connection to Postgres and gives
us a way to get a DB session inside API endpoints.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """
    FastAPI dependency — gives each request its own DB session and
    makes sure it's closed afterward, even if the request fails.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
