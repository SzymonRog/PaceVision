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

SIDE CONVENTION
---------------
All bilateral angles (knee, hip, ankle, arm) are computed for **both**
left and right sides independently.  Results are keyed as
``"left_knee_flexion"`` / ``"right_knee_flexion"`` etc.

Trunk lean is also computed per-side (left ear→shoulder→hip and
right ear→shoulder→hip) so both values are visible.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from schemas.angles import AngleResult
from schemas.landmarks import ProcessedLandmark



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
    "ankle_dorsiflexion": {
        "left": (25, 27, 31),   # knee → ankle → foot_index
        "right": (26, 28, 32),
    },
    "arm_swing": {
        "left": (11, 13, 15),   # shoulder → elbow → wrist (elbow bend)
        "right": (12, 14, 16),
    },
    "arm_drive": {
        "left": (23, 11, 13),   # hip → shoulder → elbow (shoulder flexion/extension)
        "right": (24, 12, 14),
    },
}

# Trunk lean is NOT bilateral — it uses a midline method (averaged
# shoulders and hips) measured in 2D relative to vertical.  This avoids
# the severe z-axis noise on the occluded side in side-view footage.
# Landmarks needed: left_shoulder(11), right_shoulder(12),
#                    left_hip(23), right_hip(24).
TRUNK_LEAN_LANDMARKS: tuple[int, ...] = (11, 12, 23, 24)


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
        """DEPRECATED — use trunk_lean_midline instead."""
        return AngleCalculator.angle_3d(ear, shoulder, hip)

    @staticmethod
    def trunk_lean_midline(
        left_shoulder: Point3D,
        right_shoulder: Point3D,
        left_hip: Point3D,
        right_hip: Point3D,
    ) -> float:
        """Trunk forward lean in clinical degrees (0° = upright, positive = forward).

        Computes the angle between the midline trunk segment (avg shoulders →
        avg hips) and a true vertical line, using only X-Y (sagittal plane)
        coordinates.  This matches the gait-lab convention (C7-L4 midline
        relative to gravity vector) and eliminates the z-axis noise that
        plagues bilateral ear→shoulder→hip calculations on side-view video.
        """
        mid_sh = np.array([
            (left_shoulder.x + right_shoulder.x) / 2,
            (left_shoulder.y + right_shoulder.y) / 2,
        ])
        mid_hp = np.array([
            (left_hip.x + right_hip.x) / 2,
            (left_hip.y + right_hip.y) / 2,
        ])

        # Trunk vector: shoulder → hip (points downward in world coords)
        trunk = mid_hp - mid_sh
        # Vertical vector: straight down.  MediaPipe WORLD landmarks use a
        # y-DOWN convention (larger y = closer to ground), so "down" is
        # +y.  Measuring the trunk segment against +y gives the clinical
        # forward-lean angle directly (0° = upright).
        vertical = np.array([0.0, 1.0])

        cos_theta = np.dot(trunk, vertical) / (
            np.linalg.norm(trunk) * np.linalg.norm(vertical) + 1e-10
        )
        angle_deg = float(np.degrees(np.arccos(np.clip(cos_theta, -1.0, 1.0))))

        # angle_deg is the deviation from vertical — directly the clinical
        # forward lean angle (0° = perfectly upright).
        return angle_deg

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
    ) -> dict[str, AngleResult]:
        """Compute all PaceVision angles for one frame, both sides.

        Returns keys like ``"left_knee_flexion"``, ``"right_knee_flexion"``,
        etc.  Each bilateral angle is computed independently so the user
        can see front-leg vs back-leg differences during running.

        Parameters
        ----------
        landmarks : list[ProcessedLandmark]
            Full 33-landmark list (indexed by landmark index).

        Returns
        -------
        dict mapping ``"{side}_{angle_name}"`` to ``AngleResult``.
        """
        lm_by_idx = {lm.index: lm for lm in landmarks}
        results: dict[str, AngleResult] = {}

        # ── Bilateral angles (knee, hip, ankle, arm) ────────────────
        for angle_name, sides in ANGLE_LANDMARKS.items():
            for side in ("left", "right"):
                idx_a, idx_b, idx_c = sides[side]

                # Skip if any required landmark is missing
                if not all(i in lm_by_idx for i in (idx_a, idx_b, idx_c)):
                    continue

                a = self._to_point(lm_by_idx[idx_a])
                b = self._to_point(lm_by_idx[idx_b])
                c = self._to_point(lm_by_idx[idx_c])

                value = self.angle_3d(a, b, c)
                full_name = f"{side}_{angle_name}"

                results[full_name] = AngleResult(
                    name=full_name,
                    value_deg=round(value, 2),
                    landmarks_used=(idx_a, idx_b, idx_c),
                )

        # ── Midline trunk lean (single value, not bilateral) ────────
        if all(i in lm_by_idx for i in TRUNK_LEAN_LANDMARKS):
            trunk_deg = self.trunk_lean_midline(
                self._to_point(lm_by_idx[11]),
                self._to_point(lm_by_idx[12]),
                self._to_point(lm_by_idx[23]),
                self._to_point(lm_by_idx[24]),
            )
            results["trunk_lean"] = AngleResult(
                name="trunk_lean",
                value_deg=round(trunk_deg, 2),
                landmarks_used=(11, 12, 23),  # representative triple
            )

        return results

    # ── helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _to_point(lm: ProcessedLandmark) -> Point3D:
        return Point3D(x=lm.x, y=lm.y, z=lm.z)
