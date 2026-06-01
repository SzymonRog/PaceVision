"""
LandmarkProcessor — extraction, filtering, and conversion of MediaPipe landmarks.

Converts raw MediaPipe landmark objects into our Pydantic schemas,
handles confidence filtering, and provides the ankle/heel fallback
strategy documented in CLAUDE.md.
"""

from __future__ import annotations

from schemas.landmarks import RawLandmark
from core.config import settings


# ── MediaPipe 33-landmark name map ────────────────────────────────────────────

LANDMARK_NAMES: dict[int, str] = {
    0:  "nose",
    1:  "left_eye_inner",
    2:  "left_eye",
    3:  "left_eye_outer",
    4:  "right_eye_inner",
    5:  "right_eye",
    6:  "right_eye_outer",
    7:  "left_ear",
    8:  "right_ear",
    9:  "mouth_left",
    10: "mouth_right",
    11: "left_shoulder",
    12: "right_shoulder",
    13: "left_elbow",
    14: "right_elbow",
    15: "left_wrist",
    16: "right_wrist",
    17: "left_pinky",
    18: "right_pinky",
    19: "left_index",
    20: "right_index",
    21: "left_thumb",
    22: "right_thumb",
    23: "left_hip",
    24: "right_hip",
    25: "left_knee",
    26: "right_knee",
    27: "left_ankle",
    28: "right_ankle",
    29: "left_heel",
    30: "right_heel",
    31: "left_foot_index",
    32: "right_foot_index",
}

# Indices relevant to PaceVision's angle calculations.
# Face (0-6, 9-10) and hand (17-22) landmarks are excluded — they are not
# used in any angle calculation and skipping them saves ~42% of smoothing work.
KEY_LANDMARK_INDICES: set[int] = {
    7, 8,                # ears (trunk lean)
    11, 12, 13, 14,      # shoulders, elbows (arm swing, hip/trunk)
    15, 16,              # wrists (arm swing)
    23, 24, 25, 26,      # hips, knees
    27, 28, 29, 30,      # ankles, heels (heel = ankle fallback)
    31, 32,              # foot indices (dorsiflexion)
}

# Skeleton connections for overlay — only body, no face/hands.
POSE_CONNECTIONS: frozenset[tuple[int, int]] = frozenset([
    (11, 12),                                               # shoulder bar
    (11, 13), (13, 15),                                     # left arm
    (12, 14), (14, 16),                                     # right arm
    (11, 23), (12, 24), (23, 24),                           # torso
    (23, 25), (25, 27), (27, 29), (27, 31), (29, 31),      # left leg
    (24, 26), (26, 28), (28, 30), (28, 32), (30, 32),      # right leg
])


class LandmarkProcessor:
    """Converts and filters MediaPipe landmarks into PaceVision schemas."""

    @staticmethod
    def extract_world_landmarks(
        mp_world_lms,
        *,
        key_only: bool = True,
    ) -> list[RawLandmark]:
        """Convert a MediaPipe world-landmark list to ``RawLandmark`` objects.

        Parameters
        ----------
        mp_world_lms : list
            ``result.pose_world_landmarks[0]`` — one entry per landmark.
            Each element has .x, .y, .z, .visibility, .presence attributes.
        key_only : bool
            If True (default), only return landmarks in
            ``KEY_LANDMARK_INDICES``.  Skips face/hand landmarks that
            are not used in angle calculations, saving smoothing work.
        """
        return [
            RawLandmark(
                index=idx,
                name=LANDMARK_NAMES.get(idx, f"landmark_{idx}"),
                x=lm.x,
                y=lm.y,
                z=lm.z,
                visibility=lm.visibility,
                presence=getattr(lm, "presence", lm.visibility),
            )
            for idx, lm in enumerate(mp_world_lms)
            if not key_only or idx in KEY_LANDMARK_INDICES
        ]

    @staticmethod
    def filter_by_confidence(
        landmarks: list[RawLandmark],
        threshold: float | None = None,
    ) -> list[RawLandmark]:
        """Keep only landmarks above the visibility threshold."""
        thr = threshold if threshold is not None else settings.visibility_threshold
        return [lm for lm in landmarks if lm.visibility >= thr]

    @staticmethod
    def filter_key_landmarks(landmarks: list[RawLandmark]) -> list[RawLandmark]:
        """Keep only the landmarks used for PaceVision angle calculations."""
        return [lm for lm in landmarks if lm.index in KEY_LANDMARK_INDICES]

    @staticmethod
    def get_landmark(
        landmarks: list[RawLandmark], index: int,
    ) -> RawLandmark | None:
        """Return a specific landmark by its index, or None if absent."""
        for lm in landmarks:
            if lm.index == index:
                return lm
        return None

    @staticmethod
    def get_ankle_or_heel(
        landmarks: list[RawLandmark],
        side: str = "left",
        threshold: float | None = None,
    ) -> RawLandmark | None:
        """Return ankle landmark, falling back to heel if ankle is noisy.

        The ankle landmark (27/28) is known to be noisy in MediaPipe.
        When its visibility drops below *threshold*, we substitute
        the heel landmark (29/30) which tends to be more stable.
        """
        thr = threshold if threshold is not None else settings.visibility_threshold
        ankle_idx = 27 if side == "left" else 28
        heel_idx = 29 if side == "left" else 30

        ankle = LandmarkProcessor.get_landmark(landmarks, ankle_idx)
        if ankle is not None and ankle.visibility >= thr:
            return ankle

        return LandmarkProcessor.get_landmark(landmarks, heel_idx)
