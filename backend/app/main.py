"""
PHC Supply Chain Backend — FastAPI Application Entry Point
==========================================================
Local development:
    cd backend
    uvicorn app.main:app --reload --port 8000

API docs:
    http://localhost:8000/docs   (Swagger UI)
    http://localhost:8000/redoc  (ReDoc)
"""

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from sqlalchemy.exc import SQLAlchemyError

# ── Path setup ────────────────────────────────────────────────────────────────

# This file lives at:  <repo>/backend/app/main.py
# So:
#   _BACKEND_DIR  = <repo>/backend/
#   _REPO_ROOT    = <repo>/
_BACKEND_DIR = Path(__file__).resolve().parent.parent   # backend/
_REPO_ROOT   = _BACKEND_DIR.parent                      # repo root

# Make sure ai_integration is importable
_AI_PARENT = _BACKEND_DIR                               # backend/ contains ai_integration/
if str(_AI_PARENT) not in sys.path:
    sys.path.insert(0, str(_AI_PARENT))

# Load .env from backend/ first, then repo root as fallback
load_dotenv(_BACKEND_DIR / ".env")
load_dotenv(_REPO_ROOT / ".env")

# ── Database + routes ─────────────────────────────────────────────────────────

from app.core.database import engine, Base
from app.routes        import phcs, inventory, vendors, orders, analytics, ai

# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        Base.metadata.create_all(bind=engine)
    except SQLAlchemyError:
        # Vercel's deployment filesystem is read-only; the API can still start
        # when a persistent database is not yet configured.
        pass
    yield


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title       = "PHC Supply Chain API",
    description = (
        "Backend — Core API & Business Logic for the Autonomous PHC Medicine "
        "Replenishment & Supply Chain Resilience Engine. "
        "Hackathon: Build with AI: Code for Communities (Google Cloud, 2026)."
    ),
    version     = "1.0.0",
    lifespan    = lifespan,
    docs_url    = "/docs",
    redoc_url   = "/redoc",
)

# ── CORS ──────────────────────────────────────────────────────────────────────

_raw_origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:5173,http://localhost:8000",
)
cors_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

# On Vercel the frontend is served by the same function, so relative-URL API
# calls never hit CORS at all.  The list below covers local dev and any
# separately-hosted frontend you add later.
app.add_middleware(
    CORSMiddleware,
    allow_origins     = cors_origins,
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

API_V1 = "/api/v1"

app.include_router(phcs.router,       prefix=API_V1)
app.include_router(inventory.router,  prefix=API_V1)
app.include_router(vendors.router,    prefix=API_V1)
app.include_router(orders.router,     prefix=API_V1)
app.include_router(analytics.router,  prefix=API_V1)
app.include_router(ai.router,         prefix=API_V1)

# ── Static file serving ───────────────────────────────────────────────────────

_FRONTEND_DIR = _REPO_ROOT / "frontend"
_DASHBOARD    = _FRONTEND_DIR / "dashboard" / "index.html"
_WORKER       = _FRONTEND_DIR / "worker"    / "index.html"

# Serve the admin dashboard at root
@app.get("/", tags=["Frontend"])
def serve_dashboard():
    if _DASHBOARD.exists():
        return FileResponse(str(_DASHBOARD), media_type="text/html")
    return {"message": "PHC Supply Chain API is running. See /docs for the API reference."}


# Serve the field-worker app at /worker
@app.get("/worker", tags=["Frontend"], include_in_schema=False)
def serve_worker():
    if _WORKER.exists():
        return FileResponse(str(_WORKER), media_type="text/html")
    return {"message": "Worker app not found."}


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"])
def health_check():
    """Liveness probe — returns 200 if the server is running."""
    return {"status": "ok", "service": "phc-backend"}
