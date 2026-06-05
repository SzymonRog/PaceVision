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
    # Model variant: "heavy" (most accurate, most memory), "full", or "lite"
    # (smallest footprint). Override on memory-constrained hosts with
    # PACE_MODEL_VARIANT=full to avoid OOM kills during analysis. The image
    # bakes the "heavy" model; other variants are downloaded on first use.
    model_variant: str = "heavy"

    @property
    def _variant(self) -> str:
        v = self.model_variant.lower()
        return v if v in ("heavy", "full", "lite") else "heavy"

    @property
    def model_path(self) -> str:
        return str(
            _BACKEND_DIR / "prototype" / f"pose_landmarker_{self._variant}.task"
        )

    @property
    def model_url(self) -> str:
        return (
            "https://storage.googleapis.com/mediapipe-models/"
            f"pose_landmarker/pose_landmarker_{self._variant}/float16/latest/"
            f"pose_landmarker_{self._variant}.task"
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
    # Default height (px) to downscale frames to for MediaPipe detection.
    # Full-resolution detection is a major memory consumer; 720 keeps
    # side-view landmark accuracy while cutting peak RAM on hi-res phone
    # footage. Clients may still override per-request (240–1080).
    detection_height_default: int = 720
    # Max jobs that may be queued or processing at once. New uploads beyond
    # this are rejected with 429 to bound disk/memory usage.
    max_active_jobs: int = 8
    # Durable storage root. In production this is a mounted Railway volume so
    # job state + annotated videos survive restarts. Falls back to a temp dir
    # locally (see JobManager) when the path is not writable.
    data_dir: str = "/data"
    # Completed/failed jobs (and their shareable links) live this long before
    # their data and files are reclaimed. Default 24h.
    job_ttl_sec: int = 86400
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
