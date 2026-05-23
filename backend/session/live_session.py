"""
LiveSession — owns one camera + one detector + one processing pipeline.

Runs a background processing thread that:
  1. Pulls frames from ``CameraCapture``
  2. Runs MediaPipe pose detection
  3. Extracts and smooths landmarks
  4. Computes joint angles
  5. Pushes ``WSFrame`` results into an ``asyncio.Queue``
     for the WebSocket handler to consume.
  6. Encodes annotated JPEG frames into ``video_queue``
     for the MJPEG stream endpoint.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from datetime import datetime, timezone

import cv2
import numpy as np

from analysis.angles import AngleCalculator
from camera.capture import CameraCapture
from pose.detector import PoseDetector
from pose.landmarks import LandmarkProcessor, POSE_CONNECTIONS
from pose.smoothing import SavitzkyGolayBuffer
from schemas.angles import AngleResult
from schemas.landmarks import ProcessedLandmark
from schemas.ws import WSFrame
from core.config import settings

# BGR colours for skeleton overlay
_COLOUR_OPTIMAL = (0, 200, 0)    # green
_COLOUR_WARNING = (0, 200, 255)  # yellow-orange
_COLOUR_POOR    = (0, 0, 220)    # red
_COLOUR_DEFAULT = (180, 180, 180)  # grey — no angle data

# Landmarks that belong to each angle (vertex landmark index)
_ANGLE_VERTICES = {
    "knee_flexion":        {25, 26},   # left/right knee
    "hip_flexion":         {23, 24},   # left/right hip
    "trunk_lean":          {11, 12},   # left/right shoulder
    "ankle_dorsiflexion":  {27, 28},   # left/right ankle
    "arm_swing":           {13, 14},   # left/right elbow
}


class LiveSession:
    """A single live pose-analysis session.

    Each session manages its own camera, detector, and processing thread.
    Results are pushed into ``output_queue`` for WebSocket consumers.
    """

    def __init__(
        self,
        device_index: int = 0,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.session_id: str = uuid.uuid4().hex[:12]
        self.created_at: datetime = datetime.now(timezone.utc)
        self._device_index = device_index
        self._loop = loop

        # Components (created on start)
        self._camera: CameraCapture | None = None
        self._detector: PoseDetector | None = None
        self._smoother: SavitzkyGolayBuffer | None = None
        self._angle_calc = AngleCalculator()

        # Output queue — async, consumed by the WebSocket handler
        self.output_queue: asyncio.Queue[WSFrame] = asyncio.Queue(
            maxsize=settings.output_queue_size,
        )

        # Video queue — async, consumed by the MJPEG stream endpoint
        self.video_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=2)

        # State
        self._status = "created"
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._frame_count = 0
        self._fps = 0.0
        self._error: str | None = None

    # ── properties ────────────────────────────────────────────────────

    @property
    def status(self) -> str:
        if self._error:
            return "error"
        return self._status

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def fps(self) -> float:
        return self._fps

    # ── lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Open the camera, create the detector, and launch the pipeline thread."""
        self._status = "starting"

        self._camera = CameraCapture(device_index=self._device_index)
        self._camera.start()

        self._detector = PoseDetector()
        self._smoother = SavitzkyGolayBuffer()

        self._running.set()
        self._thread = threading.Thread(
            target=self._pipeline_loop,
            name=f"session-{self.session_id}",
            daemon=True,
        )
        self._thread.start()
        self._status = "running"

    def stop(self) -> None:
        """Stop the pipeline thread and release all resources."""
        self._running.clear()

        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

        if self._camera is not None:
            self._camera.stop()
            self._camera = None

        if self._detector is not None:
            self._detector.close()
            self._detector = None

        self._smoother = None
        self._status = "stopped"

    # ── pipeline ──────────────────────────────────────────────────────

    def _pipeline_loop(self) -> None:
        """Thread target: camera → detection → smoothing → angles → output queue."""
        prev_time = time.perf_counter()

        while self._running.is_set():
            try:
                frame = self._camera.get_frame(timeout=1.0)
                if frame is None:
                    continue

                # Pose detection
                result = self._detector.detect(frame)
                if result is None:
                    # Still push raw frame to video queue so the stream stays live
                    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    if ok:
                        self._enqueue_jpeg(buf.tobytes())
                    continue

                # Extract world landmarks → RawLandmark list
                raw_landmarks = LandmarkProcessor.extract_world_landmarks(
                    result.pose_world_landmarks[0],
                )

                # Smooth landmarks
                smoothed = self._smoother.push(raw_landmarks)

                # Compute angles
                angles = self._angle_calc.compute_all(smoothed, side="left")

                # FPS
                now = time.perf_counter()
                self._fps = 1.0 / max(now - prev_time, 1e-9)
                prev_time = now
                self._frame_count += 1

                # Build output frame
                ws_frame = WSFrame(
                    session_id=self.session_id,
                    timestamp_ms=int(now * 1000),
                    frame_number=self._frame_count,
                    fps=round(self._fps, 1),
                    landmarks=smoothed,
                    angles=angles,
                )

                # Push to async output queue (thread-safe)
                self._enqueue(ws_frame)

                # Draw overlay and push JPEG to video queue
                if result.pose_landmarks:
                    annotated = self._draw_overlay(
                        frame.copy(),
                        result.pose_landmarks[0],
                        angles,
                    )
                else:
                    annotated = frame
                ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if ok:
                    self._enqueue_jpeg(buf.tobytes())

            except Exception as exc:
                self._error = str(exc)
                self._running.clear()
                break

    def _enqueue(self, frame: WSFrame) -> None:
        """Push a WSFrame into the async output queue from a worker thread."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        # Drop oldest if full — keeps latency bounded
        if self.output_queue.full():
            try:
                loop.call_soon_threadsafe(self.output_queue.get_nowait)
            except Exception:
                pass

        try:
            loop.call_soon_threadsafe(self.output_queue.put_nowait, frame)
        except Exception:
            pass  # queue full or loop closed — drop frame

    def _enqueue_jpeg(self, jpeg: bytes) -> None:
        """Push a JPEG frame into the async video queue from a worker thread."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        if self.video_queue.full():
            try:
                loop.call_soon_threadsafe(self.video_queue.get_nowait)
            except Exception:
                pass

        try:
            loop.call_soon_threadsafe(self.video_queue.put_nowait, jpeg)
        except Exception:
            pass

    # ── overlay drawing ───────────────────────────────────────────────

    def _draw_overlay(
        self,
        frame: np.ndarray,
        norm_landmarks: list,
        angles: dict[str, AngleResult],
    ) -> np.ndarray:
        """Draw skeleton + angle ratings onto *frame* (in-place) and return it."""
        h, w = frame.shape[:2]

        # Build per-landmark colour based on angle ratings
        lm_colour: dict[int, tuple[int, int, int]] = {}
        for angle_name, result in angles.items():
            colour = {
                "optimal": _COLOUR_OPTIMAL,
                "warning": _COLOUR_WARNING,
                "poor":    _COLOUR_POOR,
            }.get(result.rating, _COLOUR_DEFAULT)
            for idx in _ANGLE_VERTICES.get(angle_name, set()):
                lm_colour[idx] = colour

        # Draw connections
        for a_idx, b_idx in POSE_CONNECTIONS:
            if a_idx >= len(norm_landmarks) or b_idx >= len(norm_landmarks):
                continue
            lm_a = norm_landmarks[a_idx]
            lm_b = norm_landmarks[b_idx]
            if lm_a.visibility < 0.3 or lm_b.visibility < 0.3:
                continue
            pt_a = (int(lm_a.x * w), int(lm_a.y * h))
            pt_b = (int(lm_b.x * w), int(lm_b.y * h))
            cv2.line(frame, pt_a, pt_b, _COLOUR_DEFAULT, 2, cv2.LINE_AA)

        # Draw joint circles
        for idx, lm in enumerate(norm_landmarks):
            if lm.visibility < 0.3:
                continue
            pt = (int(lm.x * w), int(lm.y * h))
            colour = lm_colour.get(idx, _COLOUR_DEFAULT)
            cv2.circle(frame, pt, 5, colour, -1, cv2.LINE_AA)
            cv2.circle(frame, pt, 5, (255, 255, 255), 1, cv2.LINE_AA)

        # Angle labels
        y_offset = 24
        for name, result in angles.items():
            colour = {
                "optimal": _COLOUR_OPTIMAL,
                "warning": _COLOUR_WARNING,
                "poor":    _COLOUR_POOR,
            }.get(result.rating, _COLOUR_DEFAULT)
            label = f"{name}: {result.value_deg:.1f}° [{result.rating}]"
            cv2.putText(
                frame, label, (10, y_offset),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA,
            )
            cv2.putText(
                frame, label, (10, y_offset),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, colour, 1, cv2.LINE_AA,
            )
            y_offset += 22

        return frame
