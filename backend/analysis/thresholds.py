"""
Biomechanics threshold constants and scoring for PaceVision.

Each threshold defines the *optimal* range for a given metric.
Values outside this range are scored as "warning" (close) or "poor" (far).
"""

# (min_optimal, max_optimal) in degrees or SPM
THRESHOLDS: dict[str, tuple[float, float]] = {
    "knee_flexion":       (25.0, 45.0),
    "hip_flexion":        (60.0, 70.0),
    "trunk_lean":         (5.0, 12.0),
    "ankle_dorsiflexion": (18.0, 25.0),
    "cadence_spm":        (170.0, 185.0),
}

# How far outside optimal (in degrees) before "warning" becomes "poor"
_WARNING_MARGIN = 10.0


def score_angle(name: str, value: float) -> str:
    """Score a metric value against its optimal range.

    Returns
    -------
    ``"optimal"`` if within range, ``"warning"`` if within margin,
    ``"poor"`` if far outside.
    """
    lo, hi = THRESHOLDS.get(name, (0.0, 180.0))

    if lo <= value <= hi:
        return "optimal"

    distance = min(abs(value - lo), abs(value - hi))
    if distance <= _WARNING_MARGIN:
        return "warning"

    return "poor"
