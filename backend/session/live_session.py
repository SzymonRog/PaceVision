"""
LiveSession — owns one camera + one detector + one processing pipeline.

Runs a background processing thread that:
  1. Pulls frames from ``CameraCapture``
  2. Runs MediaPipe pose detection
  3. Extracts and smooths landmarks
  4. Computes joint angles
  5. Pushes ``WSFrame`` results into an ``asyncio.Queue``
     for the WebSocket handler to consume.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from datetime import datetime, timezone

from analysis.angles import AngleCalculator
from camera.capture import CameraCapture
from pose.detector import PoseDetector
from pose.landmarks import LandmarkProcessor
from pose.smoothing import SavitzkyGolayBuffer
from schemas.angles import AngleResult
from schemas.landmarks import ProcessedLandmark
from schemas.ws import WSFrame
from core.config import settings


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
