"""Stride-level outlier rejection using Median Absolute Deviation (MAD).

Removes measurement noise before form-problem detectors run.  A stride
is flagged as an outlier **per metric** (not globally) — a single noisy
knee-flexion reading doesn't discard the stride's hip-extension data.

The MAD method is preferred over z-score for gait data because it is
robust to the outliers themselves skewing the mean/std.

    outlier if: |value - median| > 2.5 * 1.4826 * MAD

where 1.4826 is the consistency constant for normal distributions and
MAD = median(|values - median(values)|).
"""

from __future__ import annotations

import numpy as np


# Consistency constant for MAD → std-equivalent under normality
_MAD_SCALE = 1.4826
_MAD_THRESHOLD = 2.5


def mad_outlier_mask(values: list[float] | np.ndarray) -> np.ndarray:
    """Return a boolean mask where True = outlier.

    Parameters
    ----------
    values : array-like
        One value per stride for a single metric.

    Returns
    -------
    np.ndarray of bool, same length as *values*.
    True entries are outliers that should be excluded.
    """
    arr = np.asarray(values, dtype=np.float64)
    if len(arr) < 3:
        # Too few values to reliably detect outliers
        return np.zeros(len(arr), dtype=bool)

    median = np.median(arr)
    mad = np.median(np.abs(arr - median))

    if mad < 1e-9:
        # All values are (nearly) identical — no outliers
        return np.zeros(len(arr), dtype=bool)

    threshold = _MAD_THRESHOLD * _MAD_SCALE * mad
    return np.abs(arr - median) > threshold


def filter_outlier_strides(
    values: list[float],
    frame_numbers: list[int],
) -> tuple[list[float], list[int], int]:
    """Remove outlier strides from a metric series.

    Parameters
    ----------
    values : list[float]
        One metric value per stride.
    frame_numbers : list[int]
        Corresponding frame numbers (same length as *values*).

    Returns
    -------
    filtered_values : list[float]
    filtered_frames : list[int]
    num_excluded : int
        How many strides were rejected as outliers.
    """
    mask = mad_outlier_mask(values)
    filtered_vals = [v for v, m in zip(values, mask) if not m]
    filtered_frames = [f for f, m in zip(frame_numbers, mask) if not m]
    return filtered_vals, filtered_frames, int(mask.sum())
