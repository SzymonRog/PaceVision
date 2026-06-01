"""
Biomechanics threshold constants and scoring for PaceVision.

Each threshold defines the *optimal* range for a given metric.
Values outside this range are scored as "warning" (close) or "poor" (far).

IMPORTANT — most angle thresholds are expressed as the **geometric angle
at the vertex** returned by ``angle_3d(a, b, c)``.  A fully extended
(straight) limb measures ~180°.  Clinical "flexion" values are the
supplement: ``flexion = 180° - geometric_angle``.

**Exception:** ``trunk_lean`` is now expressed in **clinical degrees of
forward lean** (0° = upright, positive = forward lean) via the midline
method.  It is NOT a geometric vertex angle.

    Angle                     Clinical optimal     Geometric optimal
    ─────────────────────     ────────────────     ─────────────────
    Knee flexion at contact   25–45° flexion       135–155°
    Hip flexion max           60–70° flexion       110–120°
    Trunk lean mean           4–12° forward lean   (clinical, not geometric)
    Ankle dorsiflexion mid    18–25° from neutral   65–72°

Speed-adaptive thresholds
─────────────────────────
Cadence is used as a proxy for running speed.  Three bands adjust both
the scoring ranges and the form-detector thresholds:

    Band       Cadence          Range adj    Rationale
    ────       ───────          ─────────    ─────────
    slow       < 165 SPM        +15%         wider ranges, more lenient
    moderate   165–185 SPM      (default)    standard biomechanics
    fast       > 185 SPM        -10%         tighter ranges, stricter
"""

# (min_optimal, max_optimal) — see docstring for unit conventions
THRESHOLDS: dict[str, tuple[float, float]] = {
    "knee_flexion":       (135.0, 155.0),   # geometric: 180 - 45 → 180 - 25
    "hip_flexion":        (110.0, 120.0),   # geometric: 180 - 70 → 180 - 60
    "trunk_lean":         (4.0, 12.0),      # clinical: degrees of forward lean
    "ankle_dorsiflexion": (65.0, 72.0),     # geometric: 90 - 25  → 90 - 18
    "cadence_spm":        (170.0, 185.0),   # not an angle — steps per minute
}

# How far outside optimal (in degrees) before "warning" becomes "poor"
_WARNING_MARGIN = 10.0


# ── Speed bands ────────────────────────────────────────────────────────

_SLOW_CADENCE_CUTOFF = 165.0
_FAST_CADENCE_CUTOFF = 185.0

_RANGE_ADJUSTMENT: dict[str, float] = {
    "slow": 0.15,
    "moderate": 0.0,
    "fast": -0.10,
}

# Phase 6 (data-first): only the 5 flagged detectors need thresholds.
# trunk_instability_std, hip_extension_min, and arm_swing_* were removed
# when those detectors were demoted to data-only.
DETECTOR_THRESHOLDS: dict[str, dict[str, float]] = {
    "overstride_ratio":        {"slow": 0.29, "moderate": 0.25, "fast": 0.22},
    "trunk_lean_excessive":    {"slow": 17.0, "moderate": 15.0, "fast": 14.0},
    "trunk_lean_insufficient": {"slow": 1.0,  "moderate": 2.0,  "fast": 3.0},
    "vertical_oscillation_cm": {"slow": 9.5,  "moderate": 8.0,   "fast": 7.0},
}


def estimate_speed_band(cadence_spm: float) -> str:
    """Classify runner speed from cadence."""
    if cadence_spm <= 0:
        return "moderate"
    if cadence_spm < _SLOW_CADENCE_CUTOFF:
        return "slow"
    if cadence_spm > _FAST_CADENCE_CUTOFF:
        return "fast"
    return "moderate"


def get_detector_threshold(detector_id: str, speed_band: str = "moderate") -> float:
    """Look up a speed-adjusted threshold for a form detector."""
    band_vals = DETECTOR_THRESHOLDS.get(detector_id)
    if band_vals is None:
        raise KeyError(f"Unknown detector threshold: {detector_id}")
    return band_vals.get(speed_band, band_vals["moderate"])


# ── helpers ────────────────────────────────────────────────────────────

def _base_name(name: str) -> str:
    """Strip ``left_`` / ``right_`` prefix to find the threshold key."""
    for prefix in ("left_", "right_"):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def get_threshold(name: str, speed_band: str = "moderate") -> tuple[float, float]:
    """Get speed-adjusted optimal range for an angle metric.

    Cadence thresholds are not adjusted (cadence IS the speed proxy).
    """
    base = _base_name(name)
    lo, hi = THRESHOLDS.get(base, (0.0, 180.0))

    if base == "cadence_spm":
        return lo, hi

    adj = _RANGE_ADJUSTMENT.get(speed_band, 0.0)
    if adj == 0.0:
        return lo, hi

    width = hi - lo
    delta = width * abs(adj)
    if adj > 0:
        return lo - delta, hi + delta
    return lo + delta, hi - delta


def score_angle(name: str, value: float, speed_band: str = "moderate") -> str:
    """Score a metric value against its optimal range.

    Accepts both bare names (``"knee_flexion"``) and side-prefixed
    names (``"left_knee_flexion"``).

    Returns
    -------
    ``"optimal"`` if within range, ``"warning"`` if within margin,
    ``"poor"`` if far outside.
    """
    lo, hi = get_threshold(name, speed_band)

    if lo <= value <= hi:
        return "optimal"

    distance = min(abs(value - lo), abs(value - hi))
    if distance <= _WARNING_MARGIN:
        return "warning"

    return "poor"
