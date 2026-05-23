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

    # ── Camera ────────────────────────────────────────────────────────
    capture_width: int = 1280
    capture_height: int = 720
    camera_warmup_frames: int = 10

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

    # ── Session limits ────────────────────────────────────────────────
    max_sessions: int = 4
    frame_queue_size: int = 2
    output_queue_size: int = 5


settings = Settings()
