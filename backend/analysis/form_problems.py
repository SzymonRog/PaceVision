"""
Phase-aware running form problem detection.

Analyses angle data and landmark positions at specific stride phases
to detect biomechanical faults.  Replaces the old static per-frame
scoring with context-aware checks that fire at the correct gait phase.

Detectors
---------
1. Overstriding          — ankle too far ahead of hip at contact
2. Heel strike           — heel lower than forefoot at contact
3. Trunk lean            — excessive / insufficient forward lean
4. Hip extension         — insufficient push-off at toe-off
5. Arm swing asymmetry   — L/R amplitude mismatch
6. Cadence               — step rate outside optimal bands
7. L/R asymmetry         — bilateral angle differences
8. Vertical oscillation  — excessive bouncing (hip y amplitude)
"""

from __future__ import annotations

import numpy as np

from analysis.thresholds import estimate_speed_band, get_detector_threshold
from schemas.analyze import (
    FormAnalysis,
    FormProblem,
    FrameAngles,
    StrideEvent,
    StrideSummary,
)


# ── constants ────────────────────────────────────────────────────────────

_MIN_STRIDES_FOR_RELIABILITY = 7
_SELF_CAL_Z = 1.5
_SELF_CAL_MIN_SAMPLES = 5

# Total cadence (steps/min) believable for running.  Outside this range the
# footage is almost certainly slow-motion (or the subject is walking), so the
# cadence flag is suppressed — see _detect_cadence.
_BELIEVABLE_TOTAL_CADENCE = (120.0, 230.0)

# ── scoring categories (Phase 5) ───────────────────────────────────────────

# Maps each FLAGGED problem_id to its scoring category (Phase 6: data-first,
# only 5 problems are flagged).  Cadence problems are matched by prefix in
# ``_category_for`` since their ids are generated dynamically.
PROBLEM_CATEGORY: dict[str, str] = {
    "overstriding":            "impact",
    "heel_strike":             "impact",
    "vertical_oscillation":    "impact",
    "excessive_trunk_lean":    "posture",
    "insufficient_trunk_lean": "posture",
}

# Problems whose detector threshold is adjusted by the speed band.
_SPEED_ADJUSTED_PROBLEMS: frozenset[str] = frozenset({
    "overstriding",
    "excessive_trunk_lean",
    "insufficient_trunk_lean",
    "vertical_oscillation",
})


def _category_for(problem_id: str) -> str | None:
    """Resolve a problem's scoring category, handling dynamic ids."""
    if problem_id in PROBLEM_CATEGORY:
        return PROBLEM_CATEGORY[problem_id]
    if problem_id.startswith("cadence"):
        return "cadence"
    return None


# ── helpers ──────────────────────────────────────────────────────────────

def _get_landmark(fa: FrameAngles, idx: int) -> tuple[float, float, float] | None:
    """Get (x, y, z) for a landmark index from a FrameAngles, or None."""
    if fa.landmarks is None:
        return None
    return fa.landmarks.get(idx)


def _frame_angles_by_number(
    frame_angles: list[FrameAngles],
) -> dict[int, FrameAngles]:
    """Build frame_number → FrameAngles lookup."""
    return {fa.frame_number: fa for fa in frame_angles}


def _events_by_phase_side(
    events: list[StrideEvent],
    phase: str,
    side: str,
) -> list[StrideEvent]:
    """Filter stride events by phase and side."""
    return [e for e in events if e.phase == phase and e.side == side]


def _detect_running_direction(frame_angles: list[FrameAngles]) -> int:
    """Return +1 if the runner faces +x, -1 if -x (the forward direction).

    MediaPipe WORLD landmarks are pelvis-centered, so the hip never
    translates (hip_x ≈ 0 every frame) — hip displacement is useless for
    direction.  Instead we use foot anatomy: the toe (foot_index, 31/32)
    points AHEAD of the heel (29/30) in the running direction.  Averaging
    ``toe_x − heel_x`` over all frames gives a robust forward sign that is
    invariant to the pelvis-centered coordinate origin.
    """
    diffs: list[float] = []
    for fa in frame_angles:
        if fa.landmarks is None:
            continue
        for toe_idx, heel_idx in ((31, 29), (32, 30)):
            toe = fa.landmarks.get(toe_idx)
            heel = fa.landmarks.get(heel_idx)
            if toe is not None and heel is not None:
                diffs.append(toe[0] - heel[0])
    if not diffs:
        return 1
    return 1 if (sum(diffs) / len(diffs)) >= 0 else -1


def _self_cal_filter(
    all_values: list[float],
    all_frames: list[int],
    threshold: float,
    *,
    above: bool = True,
) -> tuple[list[float], list[int], bool]:
    """Threshold + self-calibration filter for per-stride metrics.

    A stride is flagged only if it exceeds the population threshold AND
    either the runner's mean also exceeds it (consistent issue) or the
    stride is a z > 1.5 outlier for this runner (occasional breakdown).

    Returns
    -------
    (flagged_values, flagged_frames, filtered) where *filtered* is True
    when self-calibration actually removed some population-exceeding
    strides (i.e. the runner's distribution suppressed false positives).
    """
    if not all_values:
        return [], [], False

    exceeding = [
        (v, f) for v, f in zip(all_values, all_frames)
        if (v > threshold if above else v < threshold)
    ]
    if not exceeding:
        return [], [], False

    arr = np.array(all_values)
    mean = float(np.mean(arr))
    mean_exceeds = (mean > threshold) if above else (mean < threshold)

    if mean_exceeds:
        return [v for v, _ in exceeding], [f for _, f in exceeding], False

    if len(all_values) < _SELF_CAL_MIN_SAMPLES:
        return [v for v, _ in exceeding], [f for _, f in exceeding], False

    std = float(np.std(arr))
    if std < 1e-9:
        return [v for v, _ in exceeding], [f for _, f in exceeding], False

    result = [
        (v, f) for v, f in exceeding
        if abs(v - mean) / std > _SELF_CAL_Z
    ]
    filtered = len(result) < len(exceeding)
    return [v for v, _ in result], [f for _, f in result], filtered


# ── individual detectors ─────────────────────────────────────────────────

def _leg_length(fa: FrameAngles, side: str) -> float | None:
    """Compute hip-to-ankle distance for body-proportion normalization."""
    if fa.landmarks is None:
        return None
    hip_idx = 23 if side == "left" else 24
    ankle_idx = 27 if side == "left" else 28
    hip = fa.landmarks.get(hip_idx)
    ankle = fa.landmarks.get(ankle_idx)
    if hip is None or ankle is None:
        return None
    return float(np.sqrt(
        (hip[0] - ankle[0]) ** 2 +
        (hip[1] - ankle[1]) ** 2 +
        (hip[2] - ankle[2]) ** 2
    ))


def _forward_ratio(
    fa: FrameAngles,
    side: str,
    direction: int,
) -> float | None:
    """How far the side's ankle is AHEAD of its hip, as a fraction of leg length.

    Positive = ankle ahead of hip in the running direction (a landing/
    reaching leg).  Negative = ankle behind hip (a trailing push-off leg).
    """
    hip = _get_landmark(fa, 23 if side == "left" else 24)
    ankle = _get_landmark(fa, 27 if side == "left" else 28)
    if hip is None or ankle is None:
        return None
    leg_len = _leg_length(fa, side)
    if leg_len is None or leg_len < 0.1:
        return None
    return direction * (ankle[0] - hip[0]) / leg_len


def _detect_overstriding(
    frame_angles: list[FrameAngles],
    events: list[StrideEvent],
    fa_lookup: dict[int, FrameAngles],
    direction: int,
    speed_band: str = "moderate",
) -> list[FormProblem]:
    """Detect overstriding on the actually-landing leg at each contact.

    The landing leg is the foot that is FURTHEST AHEAD in the running
    direction (largest forward ratio) — never the trailing, bent push-off
    leg.  This makes the detector robust even if stride-side labeling is
    imperfect.  Uses body-normalized overstride ratio (ankle-ahead-of-hip /
    leg length) with speed-adaptive threshold + self-calibration.
    """
    problems: list[FormProblem] = []
    overstride_threshold = get_detector_threshold("overstride_ratio", speed_band)

    # Unique contact frames across both sides — at each, pick the landing leg.
    contact_frames = sorted({
        e.frame_number for e in events if e.phase == "initial_contact"
    })

    per_side_ratios: dict[str, list[float]] = {"left": [], "right": []}
    per_side_frames: dict[str, list[int]] = {"left": [], "right": []}

    for fn in contact_frames:
        fa = fa_lookup.get(fn)
        if fa is None:
            continue
        # Landing leg = the foot reaching furthest forward at this contact.
        best_side: str | None = None
        best_ratio: float | None = None
        for side in ("left", "right"):
            r = _forward_ratio(fa, side, direction)
            if r is None:
                continue
            if best_ratio is None or r > best_ratio:
                best_ratio = r
                best_side = side
        if best_side is None or best_ratio is None:
            continue
        per_side_ratios[best_side].append(best_ratio)
        per_side_frames[best_side].append(fn)

    for side in ("left", "right"):
        all_ratios = per_side_ratios[side]
        all_ratio_frames = per_side_frames[side]
        if not all_ratios:
            continue

        contacts_count = len(all_ratios)

        flagged_ratios, overstride_frames, sc_filtered = _self_cal_filter(
            all_ratios, all_ratio_frames, overstride_threshold, above=True,
        )

        if overstride_frames:
            mean_ratio = float(np.mean(flagged_ratios))
            if mean_ratio > 0.45:
                severity = "severe"
            elif mean_ratio > 0.35:
                severity = "moderate"
            else:
                severity = "mild"

            problems.append(FormProblem(
                problem_id="overstriding",
                display_name="Overstriding",
                severity=severity,
                confidence=min(1.0, len(overstride_frames) / max(contacts_count, 1)),
                side=side,
                phase="initial_contact",
                description=(
                    f"{side.title()} foot lands {mean_ratio * 100:.0f}% of leg length "
                    f"ahead of hips at ground contact"
                ),
                recommendation=(
                    "Focus on landing with your foot closer to beneath your hips. "
                    "Try increasing cadence by 5-10%."
                ),
                occurrences=len(overstride_frames),
                total_strides=contacts_count,
                occurrence_pct=round(len(overstride_frames) / contacts_count * 100, 1),
                frames=overstride_frames,
                metric_value=round(mean_ratio, 3),
                threshold=overstride_threshold,
                metric_unit="ratio",
                self_cal_applied=sc_filtered,
            ))

    return problems


def _detect_heel_strike(
    frame_angles: list[FrameAngles],
    events: list[StrideEvent],
    fa_lookup: dict[int, FrameAngles],
) -> tuple[list[FormProblem], str]:
    """Detect strike pattern at initial contact.

    Returns (problems, strike_pattern).
    """
    strike_counts = {"heel": 0, "midfoot": 0, "forefoot": 0}
    heel_frames: list[int] = []
    total_contacts = 0

    for side in ("left", "right"):
        contacts = _events_by_phase_side(events, "initial_contact", side)
        heel_idx = 29 if side == "left" else 30
        foot_idx = 31 if side == "left" else 32

        for ev in contacts:
            fa = fa_lookup.get(ev.frame_number)
            if fa is None:
                continue
            heel = _get_landmark(fa, heel_idx)
            foot = _get_landmark(fa, foot_idx)
            if heel is None or foot is None:
                continue

            total_contacts += 1
            # MediaPipe WORLD landmarks: y-axis points downward (gravity
            # direction). Larger y = closer to ground.
            # heel.y > foot.y means heel is lower (closer to ground)
            # → heel contacts ground first → heel strike.
            dy = heel[1] - foot[1]
            if dy > 0.02:
                strike_counts["heel"] += 1
                heel_frames.append(ev.frame_number)
            elif dy < -0.02:
                strike_counts["forefoot"] += 1
            else:
                strike_counts["midfoot"] += 1

    # Determine overall pattern
    if total_contacts == 0:
        return [], "unknown"

    dominant = max(strike_counts, key=lambda k: strike_counts[k])
    dominant_pct = strike_counts[dominant] / total_contacts

    if dominant_pct < 0.6:
        pattern = "mixed"
    else:
        pattern = dominant

    problems: list[FormProblem] = []
    if strike_counts["heel"] > 0:
        pct = strike_counts["heel"] / total_contacts * 100
        if pct > 40:
            severity = "severe" if pct > 75 else "moderate" if pct > 55 else "mild"
            problems.append(FormProblem(
                problem_id="heel_strike",
                display_name="Heel Striking",
                severity=severity,
                confidence=round(dominant_pct, 2),
                side=None,
                phase="initial_contact",
                description=(
                    f"Heel strikes detected in {pct:.0f}% of ground contacts. "
                    f"Heel lands before forefoot at impact."
                ),
                recommendation=(
                    "Aim to land with a midfoot strike under your center of mass. "
                    "Slightly increase forward lean and shorten your stride."
                ),
                occurrences=strike_counts["heel"],
                total_strides=total_contacts,
                occurrence_pct=round(pct, 1),
                frames=heel_frames,
                metric_value=round(pct, 1),
                threshold=40.0,
                metric_unit="percent",
            ))

    return problems, pattern


def _detect_trunk_lean(
    frame_angles: list[FrameAngles],
    events: list[StrideEvent],
    fa_lookup: dict[int, FrameAngles],
    speed_band: str = "moderate",
) -> list[FormProblem]:
    """Phase-aware trunk lean assessment using midline clinical degrees.

    Speed-adaptive thresholds + self-calibration filtering.
    """
    problems: list[FormProblem] = []
    trunk_key = "trunk_lean"

    excessive_thresh = get_detector_threshold("trunk_lean_excessive", speed_band)
    insufficient_thresh = get_detector_threshold("trunk_lean_insufficient", speed_band)

    # Collect trunk lean at all contact frames (both sides)
    all_contacts: list[StrideEvent] = []
    for side in ("left", "right"):
        all_contacts.extend(_events_by_phase_side(events, "initial_contact", side))
    all_contacts.sort(key=lambda e: e.frame_number)

    all_vals: list[float] = []
    all_frames: list[int] = []

    for ev in all_contacts:
        fa = fa_lookup.get(ev.frame_number)
        if fa is None or trunk_key not in fa.angles:
            continue
        all_vals.append(fa.angles[trunk_key].value_deg)
        all_frames.append(ev.frame_number)

    total = len(all_vals)
    if total == 0:
        return problems

    # Excessive forward lean (self-calibrated)
    excessive_vals, excessive_frames, sc_exc = _self_cal_filter(
        all_vals, all_frames, excessive_thresh, above=True,
    )
    if excessive_frames:
        mean_val = float(np.mean(excessive_vals))
        pct = len(excessive_frames) / total * 100
        if pct > 30:
            severity = "severe" if mean_val > 22 else "moderate" if mean_val > 18 else "mild"
            problems.append(FormProblem(
                problem_id="excessive_trunk_lean",
                display_name="Excessive Forward Lean",
                severity=severity,
                confidence=round(pct / 100, 2),
                side=None,
                phase="initial_contact",
                description=(
                    f"Trunk lean averages {mean_val:.0f}° forward "
                    f"at contact ({pct:.0f}% of contacts). Optimal is 4-12°."
                ),
                recommendation=(
                    "Engage your core and think about running tall. "
                    "A slight 4-12° forward lean from the ankles is optimal."
                ),
                occurrences=len(excessive_frames),
                total_strides=total,
                occurrence_pct=round(pct, 1),
                frames=excessive_frames,
                metric_value=round(mean_val, 1),
                threshold=excessive_thresh,
                metric_unit="degrees",
                self_cal_applied=sc_exc,
            ))

    # Too upright (self-calibrated)
    upright_vals, upright_frames, sc_up = _self_cal_filter(
        all_vals, all_frames, insufficient_thresh, above=False,
    )
    if upright_frames:
        mean_val = float(np.mean(upright_vals))
        pct = len(upright_frames) / total * 100
        if pct > 30:
            problems.append(FormProblem(
                problem_id="insufficient_trunk_lean",
                display_name="Insufficient Forward Lean",
                severity="mild" if pct < 60 else "moderate",
                confidence=round(pct / 100, 2),
                side=None,
                phase="initial_contact",
                description=(
                    f"Trunk is too upright at contact — "
                    f"only {mean_val:.0f}° lean ({pct:.0f}% of contacts). "
                    f"Optimal is 4-12°."
                ),
                recommendation=(
                    "Lean slightly forward from your ankles (not waist). "
                    "Aim for 4-12° of forward lean."
                ),
                occurrences=len(upright_frames),
                total_strides=total,
                occurrence_pct=round(pct, 1),
                frames=upright_frames,
                metric_value=round(mean_val, 1),
                threshold=insufficient_thresh,
                metric_unit="degrees",
                self_cal_applied=sc_up,
            ))

    # Trunk instability (lean variability) is demoted to data-only in the
    # data-first model — the std is still available via the trunk_lean angle
    # summary, but it is no longer raised as a flagged problem.

    return problems


def _detect_cadence(
    stride_summaries: list[StrideSummary],
    confident: bool = True,
) -> list[FormProblem]:
    """Cadence assessment on the reconciled TOTAL cadence.

    All summaries carry the same reconciled total cadence (set by
    ``reconcile_cadence``), so this emits a SINGLE problem (side=None).
    When *confident* is False (the two legs disagreed), cadence is reported
    as data only and no problem is raised — avoids false flags on noisy
    occluded-leg footage.

    Cadence is the only metric that depends on real-time playback rate, so a
    value implausible for running (outside ``_BELIEVABLE_TOTAL_CADENCE``)
    almost always means slow-motion footage rather than a genuine cadence
    fault.  In that case it is reported as data but not flagged.  Spatial
    metrics (overstride, trunk lean, angles) are unaffected by slow motion.
    """
    if not confident:
        return []

    spm = next((s.cadence_spm for s in stride_summaries if s.cadence_spm > 0), 0.0)
    total_strides = sum(s.num_strides for s in stride_summaries)
    if spm <= 0:
        return []

    lo, hi = _BELIEVABLE_TOTAL_CADENCE
    if not (lo <= spm <= hi):
        # Implausible for running — almost certainly slow-motion footage.
        return []

    if spm < 160:
        return [FormProblem(
            problem_id="cadence_very_low",
            display_name="Very Low Cadence",
            severity="severe",
            confidence=0.9,
            side=None,
            phase="overall",
            description=(
                f"Cadence is {spm:.0f} SPM total — strongly associated with "
                f"overstriding and higher impact forces"
            ),
            recommendation=(
                "Increase your step rate by 5-10%. Use a metronome app set to "
                "170-180 BPM to train faster turnover."
            ),
            occurrences=total_strides,
            total_strides=total_strides,
            occurrence_pct=100.0,
            frames=[],
            metric_value=spm,
            threshold=160.0,
            metric_unit="spm",
        )]
    if spm < 170:
        return [FormProblem(
            problem_id="cadence_low",
            display_name="Below Optimal Cadence",
            severity="mild",
            confidence=0.8,
            side=None,
            phase="overall",
            description=(
                f"Cadence is {spm:.0f} SPM total — below the 170-185 SPM "
                f"optimal range"
            ),
            recommendation=(
                "Try increasing your step rate by a few percent. "
                "Higher cadence typically reduces impact and overstriding."
            ),
            occurrences=total_strides,
            total_strides=total_strides,
            occurrence_pct=100.0,
            frames=[],
            metric_value=spm,
            threshold=170.0,
            metric_unit="spm",
        )]
    if spm > 195:
        return [FormProblem(
            problem_id="cadence_very_high",
            display_name="Very High Cadence",
            severity="mild",
            confidence=0.7,
            side=None,
            phase="overall",
            description=(
                f"Cadence is {spm:.0f} SPM total — may indicate very short strides"
            ),
            recommendation=(
                "Ensure your stride length is adequate. Very high cadence with "
                "short strides can limit speed."
            ),
            occurrences=total_strides,
            total_strides=total_strides,
            occurrence_pct=100.0,
            frames=[],
            metric_value=spm,
            threshold=195.0,
            metric_unit="spm",
        )]

    return []


def _detect_asymmetry(
    frame_angles: list[FrameAngles],
    events: list[StrideEvent],
    fa_lookup: dict[int, FrameAngles],
) -> tuple[list[FormProblem], dict[str, float]]:
    """Detect systematic L/R angle differences at equivalent phases."""
    problems: list[FormProblem] = []
    asymmetry_index: dict[str, float] = {}

    # trunk_lean is now a single midline value — not bilateral, so excluded
    base_angles = ["knee_flexion", "hip_flexion", "ankle_dorsiflexion"]

    for base in base_angles:
        left_key = f"left_{base}"
        right_key = f"right_{base}"

        # Collect values at contact frames for each side
        left_vals: list[float] = []
        right_vals: list[float] = []

        for side, key, vals in [("left", left_key, left_vals), ("right", right_key, right_vals)]:
            contacts = _events_by_phase_side(events, "initial_contact", side)
            for ev in contacts:
                fa = fa_lookup.get(ev.frame_number)
                if fa is not None and key in fa.angles:
                    vals.append(fa.angles[key].value_deg)

        if not left_vals or not right_vals:
            continue

        mean_l = float(np.mean(left_vals))
        mean_r = float(np.mean(right_vals))
        avg = (mean_l + mean_r) / 2
        if avg <= 0:
            continue

        asi = abs(mean_l - mean_r) / avg * 100
        asymmetry_index[base] = round(asi, 1)

        if asi > 10.0:
            weaker = "left" if mean_l < mean_r else "right"
            problems.append(FormProblem(
                problem_id=f"asymmetry_{base}",
                display_name=f"{base.replace('_', ' ').title()} Asymmetry",
                severity="moderate" if asi > 20 else "mild",
                confidence=round(min(1.0, asi / 30), 2),
                side=weaker,
                phase="initial_contact",
                description=(
                    f"{base.replace('_', ' ').title()}: left {mean_l:.1f} vs "
                    f"right {mean_r:.1f} ({asi:.0f}% asymmetry)"
                ),
                recommendation=(
                    f"Significant {base.replace('_', ' ')} asymmetry may indicate "
                    f"compensatory movement or injury. Consider a gait analysis "
                    f"with a physiotherapist."
                ),
                occurrences=min(len(left_vals), len(right_vals)),
                total_strides=min(len(left_vals), len(right_vals)),
                occurrence_pct=100.0,
                frames=[],
                metric_value=round(asi, 1),
                threshold=10.0,
                metric_unit="percent",
            ))

    return problems, asymmetry_index


def _midline_hip_y(fa: FrameAngles) -> float | None:
    """Return average y of left and right hip landmarks, or None."""
    if fa.landmarks is None:
        return None
    left = fa.landmarks.get(23)
    right = fa.landmarks.get(24)
    if left is not None and right is not None:
        return (left[1] + right[1]) / 2
    if left is not None:
        return left[1]
    if right is not None:
        return right[1]
    return None


def _detect_vertical_oscillation(
    frame_angles: list[FrameAngles],
    events: list[StrideEvent],
    fa_lookup: dict[int, FrameAngles],
    speed_band: str = "moderate",
) -> list[FormProblem]:
    """Detect excessive vertical bouncing via midline hip y-coordinate amplitude.

    Speed-adaptive threshold.
    """
    problems: list[FormProblem] = []
    osc_threshold_cm = get_detector_threshold("vertical_oscillation_cm", speed_band)
    osc_threshold_m = osc_threshold_cm / 100.0

    # Merge all contacts from both sides into one sorted list
    all_contacts: list[StrideEvent] = []
    for side in ("left", "right"):
        all_contacts.extend(_events_by_phase_side(events, "initial_contact", side))
    all_contacts.sort(key=lambda e: e.frame_number)

    if len(all_contacts) < 2:
        return problems

    amplitudes: list[float] = []
    stride_frames: list[int] = []
    excessive_frames: list[int] = []

    for i in range(len(all_contacts) - 1):
        start = all_contacts[i].frame_number
        end = all_contacts[i + 1].frame_number

        ys = [
            y
            for fa in frame_angles
            if start <= fa.frame_number <= end
            for y in [_midline_hip_y(fa)]
            if y is not None
        ]
        if len(ys) < 3:
            continue

        amp = max(ys) - min(ys)
        amplitudes.append(amp)
        stride_frames.append(all_contacts[i].frame_number)
        if amp > osc_threshold_m:
            excessive_frames.append(all_contacts[i].frame_number)

    if not amplitudes:
        return problems

    mean_amp = float(np.mean(amplitudes))
    if mean_amp > osc_threshold_m:
        severity = "severe" if mean_amp > 0.12 else "moderate" if mean_amp > 0.10 else "mild"
        problems.append(FormProblem(
            problem_id="vertical_oscillation",
            display_name="Excessive Vertical Oscillation",
            severity=severity,
            confidence=round(len(excessive_frames) / max(len(amplitudes), 1), 2),
            side=None,
            phase="stride_cycle",
            description=(
                f"Average vertical bounce of {mean_amp * 100:.1f}cm per stride"
            ),
            recommendation=(
                "Focus on running forward, not upward. Slightly increase cadence "
                "and think about keeping your head level."
            ),
            occurrences=len(excessive_frames),
            total_strides=len(amplitudes),
            occurrence_pct=round(len(excessive_frames) / max(len(amplitudes), 1) * 100, 1),
            frames=excessive_frames,
            metric_value=round(mean_amp * 100, 1),
            threshold=osc_threshold_cm,
            metric_unit="centimeters",
        ))

    return problems


# ── gating ───────────────────────────────────────────────────────────────

def _has_consecutive(frames: list[int], all_contact_frames: list[int], n: int = 2) -> bool:
    """Check if any *n* consecutive contact frames appear in *frames*.

    *all_contact_frames* must be sorted chronologically — the ordered
    list of all initial-contact frame numbers for the relevant side.
    """
    if len(frames) < n or len(all_contact_frames) < n:
        return False

    problem_set = set(frames)
    run = 0
    for cf in all_contact_frames:
        if cf in problem_set:
            run += 1
            if run >= n:
                return True
        else:
            run = 0
    return False


def _assign_tier(
    problem: FormProblem,
    all_contact_frames: list[int],
) -> FormProblem:
    """Assign a visibility tier to a problem based on occurrence pattern.

    Tiers:
        consistent  — >30% of strides
        intermittent — 15-30% OR 2+ consecutive strides
        isolated    — <15% AND not consecutive
    """
    pct = problem.occurrence_pct
    consecutive = _has_consecutive(problem.frames, all_contact_frames, n=2)

    if pct > 30:
        tier = "consistent"
    elif pct >= 15 or consecutive:
        tier = "intermittent"
    else:
        tier = "isolated"

    problem.tier = tier
    return problem


def _gate_problems(
    problems: list[FormProblem],
    stride_events: list[StrideEvent],
) -> list[FormProblem]:
    """Apply hybrid occurrence + consecutive gating to all problems.

    Problems that don't meet the minimum gate (>=15% OR 2+ consecutive)
    are kept but marked as "isolated" tier.  The caller can decide
    whether to display them.
    """
    # Build per-side sorted contact frame lists
    contact_frames: dict[str | None, list[int]] = {}
    for ev in stride_events:
        if ev.phase == "initial_contact":
            contact_frames.setdefault(ev.side, []).append(ev.frame_number)
    # Add a combined list for side=None problems
    all_frames = sorted(
        ev.frame_number for ev in stride_events if ev.phase == "initial_contact"
    )
    contact_frames[None] = all_frames

    for side_frames in contact_frames.values():
        side_frames.sort()

    gated: list[FormProblem] = []
    for p in problems:
        frames_for_side = contact_frames.get(p.side, all_frames)
        _assign_tier(p, frames_for_side)
        gated.append(p)

    return gated


def _annotate_metadata(
    problems: list[FormProblem],
    speed_band: str,
) -> list[FormProblem]:
    """Set category + speed_band_adjusted on each problem (Phase 5).

    ``self_cal_applied`` is set by the individual detectors that run
    self-calibration; this pass fills in the deterministic metadata.
    """
    for p in problems:
        p.category = _category_for(p.problem_id) or ""
        p.speed_band_adjusted = (
            speed_band != "moderate" and p.problem_id in _SPEED_ADJUSTED_PROBLEMS
        )
    return problems


# ── public API ───────────────────────────────────────────────────────────

def analyze_form(
    frame_angles: list[FrameAngles],
    stride_events: list[StrideEvent],
    stride_summaries: list[StrideSummary],
    *,
    cadence_confident: bool = True,
) -> FormAnalysis:
    """Run the flagged form-problem detectors and return a FormAnalysis.

    Data-first model: only 5 problems are FLAGGED — overstriding, heel
    strike, cadence, vertical oscillation, trunk lean.  Other quantities
    (asymmetry index, strike pattern, arm/hip angles) are still computed
    and returned as data but not raised as problems.

    Parameters
    ----------
    frame_angles : list[FrameAngles]
        Per-frame angle + landmark data from the video pipeline.
    stride_events : list[StrideEvent]
        Detected gait phase events.
    stride_summaries : list[StrideSummary]
        Reconciled cadence and stride count per side.
    cadence_confident : bool
        False when the two legs' cadence estimates disagreed; suppresses
        the cadence flag (cadence still reported as data).

    Returns
    -------
    FormAnalysis with detected problems, strike pattern, asymmetry, and score.
    """
    if not frame_angles or not stride_events:
        return FormAnalysis()

    fa_lookup = _frame_angles_by_number(frame_angles)
    direction = _detect_running_direction(frame_angles)

    # ── Speed band estimation ───────────────────────────────────────
    cadences = [ss.cadence_spm for ss in stride_summaries if ss.cadence_spm > 0]
    estimated_cadence = float(np.mean(cadences)) if cadences else 0.0
    speed_band = estimate_speed_band(estimated_cadence)

    # ── Minimum stride count check ──────────────────────────────────
    min_strides_met = True
    low_confidence_warning = None
    for ss in stride_summaries:
        if ss.num_strides < _MIN_STRIDES_FOR_RELIABILITY:
            min_strides_met = False
            low_confidence_warning = (
                f"Only {ss.num_strides} strides detected for {ss.side} side "
                f"(minimum {_MIN_STRIDES_FOR_RELIABILITY} recommended for "
                f"reliable analysis). Results may be less accurate."
            )
            break

    all_problems: list[FormProblem] = []

    # ── FLAGGED detectors (data-first set of 5) ─────────────────────
    # 1. Overstriding (landing-leg aware)
    all_problems.extend(
        _detect_overstriding(frame_angles, stride_events, fa_lookup, direction, speed_band)
    )

    # 2. Heel strike (also yields strike_pattern data)
    heel_problems, strike_pattern = _detect_heel_strike(
        frame_angles, stride_events, fa_lookup
    )
    all_problems.extend(heel_problems)

    # 3. Trunk lean (excessive / insufficient)
    all_problems.extend(
        _detect_trunk_lean(frame_angles, stride_events, fa_lookup, speed_band)
    )

    # 4. Cadence — single flag on reconciled TOTAL cadence, only when the
    #    two legs agreed (cadence_confident).
    all_problems.extend(
        _detect_cadence(stride_summaries, cadence_confident)
    )

    # 5. Vertical oscillation
    all_problems.extend(
        _detect_vertical_oscillation(frame_angles, stride_events, fa_lookup, speed_band)
    )

    # ── DATA-ONLY (computed, not flagged) ───────────────────────────
    # L/R asymmetry index is returned as data; the asymmetry *problems* are
    # not raised.  Hip extension and arm swing/drive are likewise demoted —
    # their angles remain available via the angle summary, so the
    # hip extension and arm swing/drive are likewise demoted — those angles
    # remain available via the angle summary, so no dedicated detector runs.
    asymmetry_index = _detect_asymmetry(
        frame_angles, stride_events, fa_lookup
    )[1]

    # ── Apply hybrid gating (tiering) ───────────────────────────────
    all_problems = _gate_problems(all_problems, stride_events)

    # ── Phase 5: per-problem metadata (category / speed-band flags) ──
    all_problems = _annotate_metadata(all_problems, speed_band)

    return FormAnalysis(
        problems=all_problems,
        strike_pattern=strike_pattern,
        asymmetry_index=asymmetry_index,
        min_strides_met=min_strides_met,
        low_confidence_warning=low_confidence_warning,
        speed_band=speed_band,
        estimated_cadence=round(estimated_cadence, 1),
    )
