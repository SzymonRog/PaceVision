"""
CameraCapture — threaded OpenCV camera reader.

Runs ``cap.read()`` in a daemon thread and pushes frames into a
``queue.Queue`` for consumption by the processing thread. Designed
so that multiple ``CameraCapture`` instances can coexist (one per session).

Platform notes
--------------
- **Windows**: uses ``cv2.CAP_DSHOW`` (DirectShow) for best compatibility.
- **Linux**: probes multiple ``/dev/videoN`` indices with ``cv2.CAP_V4L2``,
  then falls back to ``cv2.CAP_ANY``.  Rejects all-black metadata devices.
"""

from __future__ import annotations

import platform
import queue
import threading

import cv2
import numpy as np

from core.config import settings
from core.exceptions import CameraError


class CameraCapture:
    """Threaded camera reader with drop-if-full backpressure.

    Parameters
    ----------
    device_index : int
        Camera device index (0 = default webcam).
    width, height : int
        Requested capture resolution. The camera will use the closest
        supported resolution.
    queue_size : int
        Max frames buffered between capture and consumer. When full,
        the oldest frame is dropped to keep latency bounded.
    """

    def __init__(
        self,
        device_index: int = 0,
        width: int | None = None,
        height: int | None = None,
        queue_size: int | None = None,
    ) -> None:
        self._device_index = device_index
        self._width = width or settings.capture_width
        self._height = height or settings.capture_height
        self._queue: queue.Queue[np.ndarray] = queue.Queue(
            maxsize=queue_size or settings.frame_queue_size,
        )
        self._cap: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None
        self._running = threading.Event()

    # ── lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Open the camera and begin capturing in a background thread."""
        self._cap = self._open_camera(self._device_index)
        self._running.set()
        self._thread = threading.Thread(
            target=self._capture_loop,
            name=f"cam-{self._device_index}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the capture thread to stop and release the camera."""
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    # ── frame access ──────────────────────────────────────────────────

    def get_frame(self, timeout: float = 1.0) -> np.ndarray | None:
        """Get the next captured frame (blocking, with timeout).

        Returns ``None`` if no frame is available within *timeout* seconds.
        Called from the processing thread (not async).
        """
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    # ── internal ──────────────────────────────────────────────────────

    def _capture_loop(self) -> None:
        """Thread target: reads frames and pushes them into the queue."""
        while self._running.is_set() and self._cap is not None:
            ret, frame = self._cap.read()
            if not ret or frame is None:
                continue

            frame = cv2.flip(frame, 1)  # mirror for natural interaction

            # Drop-if-full: discard oldest frame to keep latency bounded
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
            self._queue.put(frame)

    def _open_camera(self, device_index: int) -> cv2.VideoCapture:
        """Open and configure a camera, with platform-adaptive probing."""
        backends = self._get_backends()

        for backend in backends:
            cap = cv2.VideoCapture(device_index, backend)
            if not cap.isOpened():
                cap.release()
                continue

            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)

            # Warm-up: discard initial frames (some cameras send black)
            for _ in range(settings.camera_warmup_frames):
                cap.read()

            ret, frame = cap.read()
            if ret and self._frame_is_live(frame):
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                print(f"Camera opened: index={device_index}  {w}x{h}  backend={backend}")
                return cap
            cap.release()

        raise CameraError(
            f"No working camera at index {device_index}. "
            "Check that no other process is using the camera."
        )

    @staticmethod
    def _get_backends() -> list[int]:
        """Return camera backends to try, ordered by platform preference."""
        if platform.system() == "Linux":
            return [cv2.CAP_V4L2, cv2.CAP_ANY]
        if platform.system() == "Windows":
            return [cv2.CAP_DSHOW, cv2.CAP_ANY]
        return [cv2.CAP_ANY]

    @staticmethod
    def _frame_is_live(frame: np.ndarray) -> bool:
        """Reject all-black frames that metadata devices emit."""
        return frame is not None and frame.size > 0 and float(frame.mean()) > 3.0

    # ── context manager ───────────────────────────────────────────────

    def __enter__(self) -> CameraCapture:
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
