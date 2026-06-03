"""Health and debug endpoints."""

from fastapi import APIRouter, Request

from core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict:
    job_manager = request.app.state.job_manager
    return {
        "status": "ok",
        "jobs_active": job_manager.count_unfinished(),
    }

@app.middleware("http")




@router.get("/debug/config")
async def debug_config() -> dict:
    """Return current non-sensitive configuration values."""
    return {
        "min_detection_confidence": settings.min_detection_confidence,
        "smoothing_window": settings.smoothing_window,
        "smoothing_poly": settings.smoothing_poly,
        "num_poses": settings.num_poses,
        "visibility_threshold": settings.visibility_threshold,
        "max_active_jobs": settings.max_active_jobs,
        "analysis_workers": settings.analysis_workers,
    }
