"""Health and debug endpoints."""

from fastapi import APIRouter, Request

from core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict:
    manager = request.app.state.session_manager
    return {
        "status": "ok",
        "sessions_active": len(manager.list_sessions()),
    }


@router.get("/debug/config")
async def debug_config() -> dict:
    """Return current non-sensitive configuration values."""
    return {
        "capture_width": settings.capture_width,
        "capture_height": settings.capture_height,
        "min_detection_confidence": settings.min_detection_confidence,
        "smoothing_window": settings.smoothing_window,
        "smoothing_poly": settings.smoothing_poly,
        "max_sessions": settings.max_sessions,
        "num_poses": settings.num_poses,
        "visibility_threshold": settings.visibility_threshold,
    }
