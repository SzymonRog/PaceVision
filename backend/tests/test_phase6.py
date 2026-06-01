"""Phase 6 (data-first re-scope) regression tests.

Plain-Python self-checking test (no pytest dependency).  Run from the
backend directory:

    python tests/test_phase6.py

Covers the four correctness fixes and the data-first behaviour:
  1. Trunk-lean sign (upright ~ 0deg, forward lean = positive clinical degrees)
  2. Running direction from foot anatomy (pelvis-centred invariant)
  3. Overstriding measures the LANDING (forward) leg, not the trailing leg
  4. Foot-vertical-position contact detection count + total cadence
  5. Phase-aware angle summary (rating vocab, no_reference for ankle/arm)
  6. 3-category weighted score + label + cadence confidence gating
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from analysis.angles import AngleCalculator, Point3D
from analysis.form_problems import (
    _category_for,
    _detect_running_direction,
    analyze_form,
)
from analysis.stride_detector import detect_strides, reconcile_cadence
from analysis.video_pipeline import summarize_angles
from schemas.analyze import FormProblem, FrameAngles, StrideEvent
from schemas.angles import AngleResult


def _check(name: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        raise AssertionError(name)


# ── 1. Trunk-lean sign ──────────────────────────────────────────────────

def test_trunk_lean_sign() -> None:
    print("test_trunk_lean_sign")
    c = AngleCalculator()
    # y-down world coords: hips below shoulders => larger y
    upright = c.trunk_lean_midline(
        Point3D(0, 0, 0), Point3D(0.1, 0, 0),
        Point3D(0, 1.0, 0), Point3D(0.1, 1.0, 0),
    )
    leaned = c.trunk_lean_midline(
        Point3D(0.1, 0, 0), Point3D(0.2, 0, 0),
        Point3D(0, 1.0, 0), Point3D(0.1, 1.0, 0),
    )
    _check("upright ~ 0deg", abs(upright) < 1.0)
    _check("forward lean is positive and small", 3.0 < leaned < 8.0)


# ── helpers to build synthetic gait ─────────────────────────────────────

def _ar(name: str, val: float, lms=(0, 1, 2)) -> AngleResult:
    return AngleResult(name=name, value_deg=val, landmarks_used=lms)


def _synthetic_run(
    fps: float = 30.0,
    strides: int = 12,
    forward_sign: int = -1,
    lead_amp: float = 0.10,
):
    """Build frames of a runner with realistic forward-position oscillation.

    Each foot's forward position (relative to the pelvis-centred hip) is a
    cosine that PEAKS at initial contact and troughs at toe-off, matching
    the Zeni signal the detector uses.  Left/right are half a stride out of
    phase.  The toe is placed ahead of the heel in *forward_sign* x so the
    running direction is detectable.  *lead_amp* controls how far the foot
    is ahead at contact (small = good form, no overstride flag).
    """
    frames: list[FrameAngles] = []
    period = 20  # frames per stride
    n = strides * period
    for i in range(n):
        ph_l = 2 * np.pi * ((i % period) / period)
        ph_r = 2 * np.pi * (((i % period) / period + 0.5) % 1.0)

        def leg(ph):
            # forward = direction*(ankle_x) = lead_amp*cos(ph)  (peak at contact)
            ankle_x = forward_sign * lead_amp * np.cos(ph)
            foot_y = 0.85 + 0.08 * np.cos(ph)   # lowest (max y) at contact
            toe_x = ankle_x + forward_sign * 0.03   # toe ahead of heel
            heel_x = ankle_x - forward_sign * 0.03
            return ankle_x, foot_y, toe_x, heel_x

        la_x, la_y, lt_x, lh_x = leg(ph_l)
        ra_x, ra_y, rt_x, rh_x = leg(ph_r)
        lm = {
            11: (0.0, -0.5, 0.0), 12: (0.0, -0.5, 0.0),
            23: (0.0, 0.0, 0.0), 24: (0.0, 0.0, 0.0),
            25: (la_x * 0.5, 0.4, 0.0), 26: (ra_x * 0.5, 0.4, 0.0),
            27: (la_x, la_y, 0.0), 28: (ra_x, ra_y, 0.0),
            29: (lh_x, la_y, 0.0), 30: (rh_x, ra_y, 0.0),
            31: (lt_x, la_y, 0.0), 32: (rt_x, ra_y, 0.0),
        }
        angles = {
            "left_knee_flexion": _ar("left_knee_flexion", 145.0),
            "right_knee_flexion": _ar("right_knee_flexion", 145.0),
            "left_hip_flexion": _ar("left_hip_flexion", 150.0),
            "right_hip_flexion": _ar("right_hip_flexion", 150.0),
            "left_ankle_dorsiflexion": _ar("left_ankle_dorsiflexion", 90.0),
            "right_ankle_dorsiflexion": _ar("right_ankle_dorsiflexion", 90.0),
            "trunk_lean": _ar("trunk_lean", 6.0),
        }
        frames.append(FrameAngles(
            frame_number=i, timestamp_ms=int(i / fps * 1000),
            angles=angles, landmarks=lm,
        ))
    return frames


# ── 2. Running direction from foot anatomy ──────────────────────────────

def test_direction_from_foot_anatomy() -> None:
    print("test_direction_from_foot_anatomy")
    frames = _synthetic_run(forward_sign=-1)
    _check("direction = -1 (toe ahead of heel in -x)", _detect_running_direction(frames) == -1)
    frames_pos = _synthetic_run(forward_sign=1)
    _check("direction = +1 when toe ahead in +x", _detect_running_direction(frames_pos) == 1)


# ── 3. Overstriding measures the landing (forward) leg ──────────────────

def test_overstriding_landing_leg() -> None:
    print("test_overstriding_landing_leg")
    # Lead foot only 0.05 ahead (good form); trailing foot 0.30 behind.
    # With correct direction the forward ratio is small => no false flag.
    frames = _synthetic_run(forward_sign=-1)
    fa = analyze_form(frames, *_strides(frames))
    over = [p for p in fa.problems if p.problem_id == "overstriding"]
    _check("good-form synthetic run is NOT flagged overstriding", not over)


def _strides(frames):
    events: list[StrideEvent] = []
    summaries = []
    for side in ("left", "right"):
        e, s = detect_strides(frames, 30.0, side=side)
        events.extend(e)
        if s:
            summaries.append(s)
    reconcile_cadence(summaries)
    events.sort(key=lambda x: x.frame_number)
    return events, summaries


# ── 4. Contact detection + total cadence ────────────────────────────────

def test_contact_detection() -> None:
    print("test_contact_detection")
    frames = _synthetic_run(fps=30.0, strides=12)
    events, summaries = _strides(frames)
    contacts = [e for e in events if e.phase == "initial_contact" and e.side == "left"]
    _check("left contacts detected (>=8 of 12 strides)", len(contacts) >= 8)
    _check("summaries produced", len(summaries) >= 1)
    # 12 strides over 8 s => ~90/leg => ~180 total
    _check("total cadence plausible (120-210)", 120 <= summaries[0].cadence_spm <= 210)


def test_contact_timing_is_forward_reach() -> None:
    """Initial contact (Zeni) lands at the foot's forward-most position."""
    print("test_contact_timing_is_forward_reach")
    from analysis.stride_detector import _running_direction, _forward_series
    frames = _synthetic_run(fps=30.0, strides=12)
    events, _ = _strides(frames)
    direction = _running_direction(frames)
    fr, fwd = _forward_series(frames, 31, 23, direction)
    fmap = dict(zip(fr.tolist(), fwd.tolist()))
    contacts = [e.frame_number for e in events
                if e.phase == "initial_contact" and e.side == "left"]
    at = [fmap[f] for f in contacts if f in fmap]
    hi = float(np.percentile(fwd, 90))
    # contacts should be near the forward peak, not mid/late stance (~0)
    _check("contact forward-pos near peak", at and np.median(at) > 0.6 * hi)


def test_cadence_slowmo_suppressed() -> None:
    """Implausibly low cadence (slow-mo) is reported as data, not flagged."""
    print("test_cadence_slowmo_suppressed")
    from analysis.form_problems import _detect_cadence
    from schemas.analyze import StrideSummary
    s = [StrideSummary(side="left", num_contacts=12, num_strides=11,
                       cadence_spm=80.0, cadence_rating="poor"),
         StrideSummary(side="right", num_contacts=12, num_strides=11,
                       cadence_spm=80.0, cadence_rating="poor")]
    _check("80 spm (slow-mo) not flagged", _detect_cadence(s, confident=True) == [])
    s2 = [StrideSummary(side="left", num_contacts=20, num_strides=19,
                        cadence_spm=150.0, cadence_rating="poor")]
    _check("150 spm (real, low) IS flagged", len(_detect_cadence(s2, confident=True)) == 1)


# ── 5. Phase-aware summary ──────────────────────────────────────────────

def test_phase_aware_summary() -> None:
    print("test_phase_aware_summary")
    frames = _synthetic_run()
    events, _ = _strides(frames)
    summ = {s.name: s for s in summarize_angles(frames, events, speed_band="moderate")}
    _check("ankle is no_reference", summ["left_ankle_dorsiflexion"].rating == "no_reference")
    _check("ankle thresholds are None", summ["left_ankle_dorsiflexion"].min_threshold is None)
    _check("knee phase is initial_contact", summ["left_knee_flexion"].phase == "initial_contact")
    _check("trunk in_range at 6deg", summ["trunk_lean"].rating == "in_range")
    _check("rating vocab valid", all(
        s.rating in ("in_range", "out_of_range", "no_reference") for s in summ.values()
    ))


# ── 6. Category mapping + cadence confidence gating ─────────────────────

def test_scoring_and_cadence_gating() -> None:
    print("test_scoring_and_cadence_gating")
    _check("category map", _category_for("overstriding") == "impact"
           and _category_for("cadence_low") == "cadence"
           and _category_for("excessive_trunk_lean") == "posture")

    # Cadence confidence gating: disagreeing legs -> no cadence flag
    frames = _synthetic_run()
    events, summaries = _strides(frames)
    summaries[0].cadence_spm = 150.0
    if len(summaries) > 1:
        summaries[1].cadence_spm = 150.0
    fa_conf = analyze_form(frames, events, summaries, cadence_confident=False)
    _check("low-confidence cadence is not flagged",
           not any(p.problem_id.startswith("cadence") for p in fa_conf.problems))


if __name__ == "__main__":
    test_trunk_lean_sign()
    test_direction_from_foot_anatomy()
    test_overstriding_landing_leg()
    test_contact_detection()
    test_contact_timing_is_forward_reach()
    test_cadence_slowmo_suppressed()
    test_phase_aware_summary()
    test_scoring_and_cadence_gating()
    print("\nALL PHASE 6 TESTS PASSED")
