"""
PaceVision Backend — FastAPI application entry point.

Run with:
    cd backend
    uvicorn main:app --reload

Endpoints:
    GET  /health                              — health check
    GET  /debug/config                        — current settings
    POST /api/analyze-video                   — upload video for analysis
    GET  /api/analyze-video/{id}/status       — SSE progress stream
    GET  /api/analyze-video/{id}/result       — JSON analysis results + strides
    GET  /api/analyze-video/{id}/video        — download annotated MP4
    GET  /api/analyze-video/{id}/notebook     — download Jupyter notebook
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
import tempfile

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes_health import router as health_router
from api.routes_analyze import router as analyze_router
from core.config import settings
from jobs.manager import JobManager
from fastapi import Request, Response

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("pacevision")


async def _cleanup_loop(job_manager: JobManager) -> None:
    """Periodically reclaim expired jobs and their temp files."""
    while True:
        try:
            await asyncio.sleep(settings.cleanup_interval_sec)
            removed = await asyncio.to_thread(job_manager.cleanup_stale)
            if removed:
                logger.info("Cleaned up %d expired job(s).", removed)
        except asyncio.CancelledError:
            break
        except Exception:  # never let the sweeper die on a transient error
            logger.exception("Job cleanup sweep failed; will retry.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle hook."""
    temp_dir = Path(tempfile.gettempdir()) / "pacevision_jobs"
    app.state.job_manager = JobManager(temp_dir)

    cleanup_task = asyncio.create_task(_cleanup_loop(app.state.job_manager))

    logger.info("PaceVision backend started.")
    yield
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    app.state.job_manager.shutdown()
    logger.info("PaceVision backend shut down.")


app = FastAPI(
    title="PaceVision",
    description="Real-time human pose analysis API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — origins configurable via PACE_CORS_ORIGINS (comma-separated).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Needed so the browser <video> element can read range/length headers when
    # streaming the annotated MP4 cross-origin.
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)


# Register routers
app.include_router(health_router)
app.include_router(analyze_router)
