"""
Savitzky-Golay smoothing buffer for landmark coordinate streams.

Maintains a rolling window per landmark coordinate. When the buffer
reaches the configured window size, ``scipy.signal.savgol_filter`` is
applied to produce smoothed output.  Before the buffer fills, raw
values pass through unchanged.

Buffers are allocated **on demand** per landmark index, so only
landmarks that actually flow through the pipeline consume memory.
This means face/hand landmarks that are filtered out upstream never
allocate a buffer.
"""

from __future__ import annotations

from collections import deque

import numpy as np
from scipy.signal import savgol_filter

from core.config import settings
from schemas.landmarks import ProcessedLandmark, RawLandmark


class SavitzkyGolayBuffer:
    """Windowed Savitzky-Golay smoother for real-time landmark streams.

    Parameters
    ----------
    window : int
        Number of frames in the rolling window. Must be odd and >= 3.
    poly : int
        Polynomial order for the Savitzky-Golay filter. Must be < *window*.
    """

    def __init__(
        self,
        window: int | None = None,
        poly: int | None = None,
    ) -> None:
        self.window = window or settings.smoothing_window
        self.poly = poly or settings.smoothing_poly

        # Ensure window is odd (savgol_filter requirement)
        if self.window % 2 == 0:
            self.window += 1

        # Sparse buffers: allocated on first push per landmark index.
        # {landmark_index: [deque_x, deque_y, deque_z]}
        self._buffers: dict[int, list[deque[float]]] = {}
        self._frame_count = 0

    @property
    def is_ready(self) -> bool:
        """True once enough frames have been buffered for smoothing."""
        return self._frame_count >= self.window

    def push(self, raw_landmarks: list[RawLandmark]) -> list[ProcessedLandmark]:
        """Add a frame of raw landmarks and return smoothed output.

        If the buffer is not yet full, returns unsmoothed values with
        ``smoothed=False``.
        """
        for lm in raw_landmarks:
            bufs = self._buffers.get(lm.index)
            if bufs is None:
                bufs = [deque(maxlen=self.window) for _ in range(3)]
                self._buffers[lm.index] = bufs
            bufs[0].append(lm.x)
            bufs[1].append(lm.y)
            bufs[2].append(lm.z)

        self._frame_count += 1
        ready = self.is_ready

        results: list[ProcessedLandmark] = []
        for lm in raw_landmarks:
            bufs = self._buffers.get(lm.index)
            if bufs is None:
                continue

            if ready:
                x = self._smooth(bufs[0])
                y = self._smooth(bufs[1])
                z = self._smooth(bufs[2])
            else:
                x, y, z = lm.x, lm.y, lm.z

            results.append(ProcessedLandmark(
                index=lm.index,
                name=lm.name,
                x=x,
                y=y,
                z=z,
                visibility=lm.visibility,
                smoothed=ready,
            ))

        return results

    def reset(self) -> None:
        """Clear all buffered data."""
        self._buffers.clear()
        self._frame_count = 0

    def _smooth(self, buf: deque[float]) -> float:
        """Apply Savitzky-Golay filter and return the most recent smoothed value."""
        arr = np.array(buf, dtype=np.float64)
        smoothed = savgol_filter(arr, self.window, self.poly)
        return float(smoothed[-1])
