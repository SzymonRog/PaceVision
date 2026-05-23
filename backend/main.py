"""
PaceVision Backend — FastAPI application entry point.

Run with:
    cd backend
    uvicorn main:app --reload

Endpoints:
    GET  /health                 — health check
    GET  /debug/config           — current settings
    POST /api/sessions           — start a live session
    GET  /api/sessions           — list sessions
    GET  /api/sessions/{id}      — session status
    DELETE /api/sessions/{id}    — stop session
    WS   /ws/{session_id}        — real-time pose + angle stream
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes_health import router as health_router
from api.routes_session import router as session_router
from api.ws_stream import router as ws_router
from session.manager import SessionManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle hook."""
    app.state.session_manager = SessionManager()
    print("PaceVision backend started.")
    yield
    app.state.session_manager.shutdown_all()
    print("PaceVision backend shut down — all sessions released.")


app = FastAPI(
    title="PaceVision",
    description="Real-time human pose analysis API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow local frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(health_router)
app.include_router(session_router)
app.include_router(ws_router)
