"""
FastAPI application entry point for the Adaptive Stealth Network.

Provides:
    - CORS middleware for cross-origin requests.
    - Lifespan hooks for DB init/cleanup and scheduler management.
    - Inclusion of all API routers.

Run with::

    uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.database import close_db, init_db
from backend.routes import router
from backend.scheduler import start_scheduler, stop_scheduler

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("asn.app")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    On startup:
        1. Initialize database tables.
        2. Start the background metrics scheduler.

    On shutdown:
        1. Stop the scheduler.
        2. Dispose of the database engine.
    """
    logger.info("🚀 Starting Adaptive Stealth Network backend")
    await init_db()
    start_scheduler(interval_seconds=30)
    yield
    stop_scheduler()
    await close_db()
    logger.info("🛑 Backend shut down gracefully")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Adaptive Stealth Network",
    description=(
        "REST API for managing nodes, routes, and metrics in an "
        "adaptive stealth network with multi-node routing, traffic "
        "segmentation, and DPI resistance."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow all origins for development; restrict in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router
app.include_router(router)


import os

# Include API router
app.include_router(router)

# Serve Frontend Management Panel
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    from fastapi.staticfiles import StaticFiles
    # Mount the frontend directory on root. It exposes index.html automatically.
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
else:
    @app.get("/", tags=["root"])
    async def root() -> dict:
        """Root endpoint with a welcome message."""
        return {
            "name": "Adaptive Stealth Network",
            "version": "1.0.0",
            "docs": "/docs",
            "frontend_status": "Not built or missing",
        }
