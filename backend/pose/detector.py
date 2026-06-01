"""
PoseDetector — wraps the MediaPipe Tasks PoseLandmarker API.

Handles model download, landmarker creation, and per-frame inference.
Uses VIDEO running mode (synchronous, with temporal smoothing).
"""

from __future__ import annotations

import logging
import shutil
import time
import urllib.request
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision as mp_vision

from core.config import settings

logger = logging.getLogger("pacevision.detector")


class PoseDetector:
    """Synchronous pose detector using MediaPipe Tasks API (VIDEO mode).

    Each instance owns one ``PoseLandmarker``. Instances are **not**
    thread-safe — each processing context must create its own detector.
    """

    def __init__(
        self,
        model_path: str | None = None,
        min_detection_confidence: float | None = None,
        min_presence_confidence: float | None = None,
        min_tracking_confidence: float | None = None,
        num_poses: int | None = None,
    ) -> None:
        self._model_path = model_path or settings.model_path
        self.ensure_model(self._model_path, settings.model_url)

        base_options = mp_tasks.BaseOptions(
            model_asset_path=self._model_path,
        )
        options = mp_vision.PoseLandmarkerOptions(
            base_options=base_options,
            running_mode=mp_vision.RunningMode.VIDEO,
            num_poses=num_poses or settings.num_poses,
            min_pose_detection_confidence=(
                min_detection_confidence or settings.min_detection_confidence
            ),
            min_pose_presence_confidence=(
                min_presence_confidence or settings.min_presence_confidence
            ),
            min_tracking_confidence=(
                min_tracking_confidence or settings.min_tracking_confidence
            ),
        )
        self._landmarker = mp_vision.PoseLandmarker.create_from_options(options)
        self._start_ms = int(time.perf_counter() * 1000)

    # ── public API ────────────────────────────────────────────────────

    def detect(
        self, frame_bgr: np.ndarray,
    ) -> mp_vision.PoseLandmarkerResult | None:
        """Run pose detection on a single BGR frame.

        Returns the raw MediaPipe result (normalized + world landmarks),
        or ``None`` if no pose was detected.

        The caller is responsible for converting MediaPipe landmark objects
        into our Pydantic schemas via ``LandmarkProcessor``.
        """
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        timestamp_ms = int(time.perf_counter() * 1000) - self._start_ms

        result = self._landmarker.detect_for_video(mp_image, timestamp_ms)
        if not result.pose_world_landmarks:
            return None
        return result

    def close(self) -> None:
        """Release the underlying landmarker resources."""
        self._landmarker.close()

    # ── model management ──────────────────────────────────────────────

    @staticmethod
    def ensure_model(model_path: str, model_url: str) -> None:
        """Download the pose landmarker model if not already present."""
        path = Path(model_path)
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading pose model (~25 MB) -> %s ...", path)
        # Download to a temp file then rename, so an interrupted/timed-out
        # download never leaves a truncated model in place.
        tmp_path = path.with_suffix(path.suffix + ".part")
        try:
            with urllib.request.urlopen(
                model_url, timeout=settings.model_download_timeout_sec,
            ) as resp, open(tmp_path, "wb") as out:
                shutil.copyfileobj(resp, out)
            tmp_path.replace(path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        logger.info("Pose model download complete.")

    # ── context manager ───────────────────────────────────────────────

    def __enter__(self) -> PoseDetector:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
