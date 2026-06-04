"""
Centralized configuration for PaceVision backend.

All tuneable parameters live here. Values come from environment variables
(uppercased, prefixed PACE_) with sensible defaults for local development.
"""

from pathlib import Path
from pydantic_settings import BaseSettings

_BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application-wide settings, loaded once at startup."""

    model_config = {"env_prefix": "PACE_"}

    # ── MediaPipe model ───────────────────────────────────────────────
    model_path: str = str(
        _BACKEND_DIR / "prototype" / "pose_landmarker_heavy.task"
    )
    model_url: str = (
        "https://storage.googleapis.com/mediapipe-models/"
        "pose_landmarker/pose_landmarker_heavy/float16/latest/"
        "pose_landmarker_heavy.task"
    )

    # ── MediaPipe detection ───────────────────────────────────────────
    min_detection_confidence: float = 0.7
    min_presence_confidence: float = 0.7
    min_tracking_confidence: float = 0.7
    num_poses: int = 1

    # ── Landmark filtering ────────────────────────────────────────────
    visibility_threshold: float = 0.5

    # ── Smoothing (Savitzky-Golay) ────────────────────────────────────
    smoothing_window: int = 7
    smoothing_poly: int = 2

    # ── Video analysis ────────────────────────────────────────────────
    max_upload_mb: int = 500
    analysis_workers: int = 2
    # Max jobs that may be queued or processing at once. New uploads beyond
    # this are rejected with 429 to bound disk/memory usage.
    max_active_jobs: int = 8
    # Completed/failed jobs are retained this long before their data and temp
    # files are reclaimed by the periodic cleanup task.
    job_ttl_sec: int = 3600
    # How often the background task sweeps expired jobs.
    cleanup_interval_sec: int = 300
    # Timeout (seconds) for the one-time MediaPipe model download.
    model_download_timeout_sec: int = 120

    # ── CORS ──────────────────────────────────────────────────────────
    # Comma-separated list of allowed frontend origins. Override in prod with
    # PACE_CORS_ORIGINS="https://your-app.vercel.app".
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000,https://pace-vision.vercel.app"

    @property
    def cors_origin_list(self) -> list[str]:
        """Parsed, whitespace-trimmed CORS origins."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
