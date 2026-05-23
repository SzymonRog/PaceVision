"""
Savitzky-Golay smoothing buffer for landmark coordinate streams.

Maintains a rolling window per landmark coordinate (33 landmarks x 3 axes
= 99 channels). When the buffer reaches the configured window size,
``scipy.signal.savgol_filter`` is applied to produce smoothed output.
Before the buffer fills, raw values pass through unchanged.
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
    num_landmarks : int
        Expected number of landmarks per frame (33 for MediaPipe Pose).
    """

    def __init__(
        self,
        window: int | None = None,
        poly: int | None = None,
        num_landmarks: int = 33,
    ) -> None:
        self.window = window or settings.smoothing_window
        self.poly = poly or settings.smoothing_poly
        self.num_landmarks = num_landmarks

        # Ensure window is odd (savgol_filter requirement)
        if self.window % 2 == 0:
            self.window += 1

        # Rolling buffers: one deque per coordinate channel.
        # Shape conceptually: [num_landmarks, 3 (x/y/z)], each a deque of floats.
        self._buffers: list[list[deque[float]]] = [
            [deque(maxlen=self.window) for _ in range(3)]
            for _ in range(num_landmarks)
        ]
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
        # Push raw values into the rolling deques
        for lm in raw_landmarks:
            if lm.index < self.num_landmarks:
                self._buffers[lm.index][0].append(lm.x)
                self._buffers[lm.index][1].append(lm.y)
                self._buffers[lm.index][2].append(lm.z)

        self._frame_count += 1
        ready = self.is_ready

        results: list[ProcessedLandmark] = []
        for lm in raw_landmarks:
            if lm.index >= self.num_landmarks:
                continue

            if ready:
                x = self._smooth(self._buffers[lm.index][0])
                y = self._smooth(self._buffers[lm.index][1])
                z = self._smooth(self._buffers[lm.index][2])
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
        for landmark_bufs in self._buffers:
            for buf in landmark_bufs:
                buf.clear()
        self._frame_count = 0

    def _smooth(self, buf: deque[float]) -> float:
        """Apply Savitzky-Golay filter and return the most recent smoothed value."""
        arr = np.array(buf, dtype=np.float64)
        smoothed = savgol_filter(arr, self.window, self.poly)
        return float(smoothed[-1])
