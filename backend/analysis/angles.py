"""
Pure-math angle calculator for joint-angle analysis.

No MediaPipe dependency — takes 3D coordinates, returns degrees.
All methods are static so the module is stateless and fully testable
with synthetic landmark data.

MATH
----
Given three points A, B, C the angle at vertex B is:

    BA = A - B
    BC = C - B
    cos(theta) = (BA . BC) / (|BA| * |BC|)
    theta      = arccos(clamp(cos(theta), -1, 1))

We clamp to [-1, 1] to guard against floating-point drift that would
make arccos return NaN.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from schemas.angles import AngleResult
from schemas.landmarks import ProcessedLandmark

from analysis.thresholds import THRESHOLDS, score_angle


# ── Point3D ───────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class Point3D:
    """Lightweight 3D point used as input to angle calculations."""

    x: float
    y: float
    z: float

    def as_array(self) -> np.ndarray:
        return np.array([self.x, self.y, self.z], dtype=np.float64)

    def as_array_2d(self) -> np.ndarray:
        """XY only — for sagittal-plane (side-view) angle calculations."""
        return np.array([self.x, self.y], dtype=np.float64)


# ── Landmark index maps ──────────────────────────────────────────────────────
# Left / right variants for each angle's three-landmark triplet.

ANGLE_LANDMARKS: dict[str, dict[str, tuple[int, int, int]]] = {
    "knee_flexion": {
        "left": (23, 25, 27),   # hip → knee → ankle
        "right": (24, 26, 28),
    },
    "hip_flexion": {
        "left": (11, 23, 25),   # shoulder → hip → knee
        "right": (12, 24, 26),
    },
    "trunk_lean": {
        "left": (7, 11, 23),    # ear → shoulder → hip
        "right": (8, 12, 24),
    },
    "ankle_dorsiflexion": {
        "left": (25, 27, 31),   # knee → ankle → foot_index
        "right": (26, 28, 32),
    },
    "arm_swing": {
        "left": (11, 13, 15),   # shoulder → elbow → wrist
        "right": (12, 14, 16),
    },
}


# ── Core math ─────────────────────────────────────────────────────────────────

class AngleCalculator:
    """Stateless calculator for joint angles between landmark triplets."""

    # ── generic angle methods ─────────────────────────────────────────

    @staticmethod
    def angle_3d(a: Point3D, b: Point3D, c: Point3D) -> float:
        """Angle in degrees at vertex *b* using full 3D coordinates."""
        ba = a.as_array() - b.as_array()
        bc = c.as_array() - b.as_array()

        cos_theta = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-10)
        return float(np.degrees(np.arccos(np.clip(cos_theta, -1.0, 1.0))))

    @staticmethod
    def angle_2d(a: Point3D, b: Point3D, c: Point3D) -> float:
        """Angle in degrees at vertex *b* using only X-Y (sagittal plane)."""
        ba = a.as_array_2d() - b.as_array_2d()
        bc = c.as_array_2d() - b.as_array_2d()

        cos_theta = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-10)
        return float(np.degrees(np.arccos(np.clip(cos_theta, -1.0, 1.0))))

    # ── named convenience methods ─────────────────────────────────────

    @staticmethod
    def knee_flexion(hip: Point3D, knee: Point3D, ankle: Point3D) -> float:
        return AngleCalculator.angle_3d(hip, knee, ankle)

    @staticmethod
    def hip_flexion(shoulder: Point3D, hip: Point3D, knee: Point3D) -> float:
        return AngleCalculator.angle_3d(shoulder, hip, knee)

    @staticmethod
    def trunk_lean(ear: Point3D, shoulder: Point3D, hip: Point3D) -> float:
        return AngleCalculator.angle_3d(ear, shoulder, hip)

    @staticmethod
    def ankle_dorsiflexion(
        knee: Point3D, ankle: Point3D, foot: Point3D,
    ) -> float:
        return AngleCalculator.angle_3d(knee, ankle, foot)

    @staticmethod
    def arm_swing(
        shoulder: Point3D, elbow: Point3D, wrist: Point3D,
    ) -> float:
        return AngleCalculator.angle_3d(shoulder, elbow, wrist)

    # ── batch computation ─────────────────────────────────────────────

    def compute_all(
        self,
        landmarks: list[ProcessedLandmark],
        side: str = "left",
    ) -> dict[str, AngleResult]:
        """Compute all 5 PaceVision angles for one frame.

        Parameters
        ----------
        landmarks : list[ProcessedLandmark]
            Full 33-landmark list (indexed by landmark index).
        side : str
            ``"left"`` or ``"right"`` — selects which body side to measure.

        Returns
        -------
        dict mapping angle name to ``AngleResult``.
        """
        lm_by_idx = {lm.index: lm for lm in landmarks}
        results: dict[str, AngleResult] = {}

        for angle_name, sides in ANGLE_LANDMARKS.items():
            idx_a, idx_b, idx_c = sides[side]

            # Skip if any required landmark is missing
            if not all(i in lm_by_idx for i in (idx_a, idx_b, idx_c)):
                continue

            a = self._to_point(lm_by_idx[idx_a])
            b = self._to_point(lm_by_idx[idx_b])
            c = self._to_point(lm_by_idx[idx_c])

            value = self.angle_3d(a, b, c)
            lo, hi = THRESHOLDS.get(angle_name, (0.0, 180.0))
            rating = score_angle(angle_name, value)

            results[angle_name] = AngleResult(
                name=angle_name,
                value_deg=round(value, 2),
                min_threshold=lo,
                max_threshold=hi,
                rating=rating,
                landmarks_used=(idx_a, idx_b, idx_c),
            )

        return results

    # ── helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _to_point(lm: ProcessedLandmark) -> Point3D:
        return Point3D(x=lm.x, y=lm.y, z=lm.z)
