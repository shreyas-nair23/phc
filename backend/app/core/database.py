"""
Database engine and session setup.
Supports both SQLite (dev) and PostgreSQL (prod) via DATABASE_URL env var.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from dotenv import load_dotenv

load_dotenv()

_configured_database_url = (os.getenv("DATABASE_URL") or "").strip()
_deployment_environment = (
    os.getenv("VERCEL_ENV")
    or os.getenv("ENVIRONMENT")
    or os.getenv("APP_ENV")
    or ""
).strip().lower()
_read_only_runtime = os.getenv("VERCEL") == "1" or _deployment_environment in {
    "production",
    "prod",
}

if _configured_database_url.startswith("sqlite") and _read_only_runtime:
    DATABASE_URL = "sqlite:////tmp/phc.db"
elif _configured_database_url:
    DATABASE_URL = _configured_database_url
elif _read_only_runtime:
    DATABASE_URL = "sqlite:////tmp/phc.db"
else:
    DATABASE_URL = "sqlite:///./phc.db"

# SQLite needs check_same_thread=False; PostgreSQL doesn't need it
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False,          # set True to log all SQL for debugging
    pool_pre_ping=True,  # recycle stale connections gracefully
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


def get_db():
    """FastAPI dependency — yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
