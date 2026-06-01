"""
Stride phase detection from per-frame landmark + angle data.

**Phase 6 redesign (data-first):**

Initial contact is detected from the *landing foot's vertical position*
rather than knee-flexion minima.  In side-view world coordinates
(y-down), the foot reaches its LOWEST physical point — i.e. its MAXIMUM
world-y — once per stride at ground contact.  Knee flexion, by contrast,
has two minima per stride (stance absorption + swing), which the old
detector double-counted (producing ~2× cadence).

    Phase               Detection method
    ──────────────      ──────────────────────────────────────────
    Initial contact     Local MAXIMA in landing-foot world-y
                        (foot_index, fallback heel), once per stride,
                        with adaptive prominence chosen to minimise
                        inter-contact interval variability within a
                        plausible per-leg cadence band.
    Mid-stance          Between two contacts, the frame where ankle
                        dorsiflexion is at its MINIMUM.
    Toe-off             Between two contacts, the first positive
                        zero-crossing of the hip-flexion derivative.

**Selectable initial-contact method** (``contact_method``):

The forward-reach peak (Zeni et al. 2008) fires when the foot is furthest
ahead of the hip — i.e. late swing, a few frames *before* the foot plants.
That early frame samples a more extended leg and can bias contact-phase
angles (e.g. knee flexion).  Three methods are offered so the user can
compare which best matches their footage:

    forward_peak (default)  Foot furthest forward of the hip (Zeni).
    forward_peak_delayed    forward_peak shifted forward by a small
                            fixed time (~30 ms), snapped to an analyzed
                            frame.
    foot_plant              forward_peak snapped forward to the frame
                            where the foot is physically lowest
                            (max world-y) within a short window — the
                            true ground contact.

Only the *event frames* move; cadence (derived from the original peak
spacing) and the mid-stance/toe-off logic are unchanged.

Cadence is reported as **total** steps per minute (≈ per-leg × 2) so it
matches the 170–185 SPM total-cadence threshold used downstream.  The two
legs are reconciled by the pipeline after detection.
"""

from __future__ import annotations

import bisect

import numpy as np
from scipy.signal import find_peaks

from schemas.analyze import FrameAngles, StrideEvent, StrideSummary


# ── tuning constants ───────────────────────────────────────────────────

# Plausible cadence for a single leg (steps/min). Total cadence ≈ 2×.
# Wide range so it also covers slow-motion footage (low apparent cadence).
_PLAUSIBLE_PER_LEG = (30.0, 120.0)
_MIN_FOOT_SAMPLES = 12
_MIN_AUTOCORR = 0.3   # minimum autocorrelation to trust a stride period

# Initial-contact detection methods (see module docstring).
# ``foot_plant`` (true ground contact) is the default; ``forward_peak`` is the
# only method that performs no refinement.
DEFAULT_CONTACT_METHOD = "foot_plant"
CONTACT_METHODS = ("foot_plant", "forward_peak_delayed", "forward_peak")

# forward_peak_delayed: forward shift applied to each contact.
_CONTACT_DELAY_SEC = 0.03
# foot_plant: max forward search window when snapping to the lowest foot.
_PLANT_WINDOW_SEC = 0.15

# Landmark indices per side
_FOOT_IDX = {"left": 31, "right": 32}   # foot_index (toe)
_HEEL_IDX = {"left": 29, "right": 30}   # heel
_HIP_IDX = {"left": 23, "right": 24}


# ── series extraction ──────────────────────────────────────────────────

def _extract_series(
    frame_angles: list[FrameAngles],
    angle_key: str,
) -> tuple[list[int], list[int], np.ndarray]:
    """Extract a 1-D angle time-series. Returns (frames, timestamps, values)."""
    frames: list[int] = []
    timestamps: list[int] = []
    values: list[float] = []
    for fa in frame_angles:
        if angle_key in fa.angles:
            frames.append(fa.frame_number)
            timestamps.append(fa.timestamp_ms)
            values.append(fa.angles[angle_key].value_deg)
    return frames, timestamps, np.array(values, dtype=np.float64)


def _running_direction(frame_angles: list[FrameAngles]) -> int:
    """Forward sign from foot anatomy (toe ahead of heel); pelvis-invariant."""
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


def _forward_series(
    frame_angles: list[FrameAngles],
    foot_idx: int,
    hip_idx: int,
    direction: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Foot forward-position relative to the hip, in the running direction.

    Returns (frame_numbers, forward_values).  This is the Zeni et al. (2008)
    coordinate signal: it peaks at INITIAL CONTACT (foot reaches furthest
    forward) and troughs at toe-off (foot furthest back).
    """
    frames: list[int] = []
    fwd: list[float] = []
    for fa in frame_angles:
        if fa.landmarks is None:
            continue
        foot = fa.landmarks.get(foot_idx)
        hip = fa.landmarks.get(hip_idx)
        if foot is not None and hip is not None:
            frames.append(fa.frame_number)
            fwd.append(direction * (foot[0] - hip[0]))
    return np.array(frames, dtype=int), np.array(fwd, dtype=np.float64)


def _autocorr_period(sig: np.ndarray, video_fps: float) -> int | None:
    """Estimate the dominant full-stride period (frames) via autocorrelation."""
    n = len(sig)
    if n < _MIN_FOOT_SAMPLES:
        return None
    y = sig - sig.mean()
    ac = np.correlate(y, y, "full")[n - 1:]
    if ac[0] <= 1e-12:
        return None
    ac = ac / ac[0]
    lo = max(2, int(video_fps / (_PLAUSIBLE_PER_LEG[1] / 60.0)))
    hi = min(n - 1, int(video_fps / (_PLAUSIBLE_PER_LEG[0] / 60.0)))
    if hi <= lo:
        return None
    seg = ac[lo:hi + 1]
    idx = int(np.argmax(seg))
    if seg[idx] < _MIN_AUTOCORR:
        return None
    return lo + idx


def _detect_contacts_forward(
    frames: np.ndarray,
    fwd: np.ndarray,
    video_fps: float,
) -> tuple[list[int], float] | None:
    """Detect initial contacts as forward-position maxima (Zeni method).

    The stride period is estimated by autocorrelation (robust to amplitude
    noise); contacts are the forward-position peaks spaced ~one stride
    apart.  Returns (contact_frame_numbers, per_leg_cadence_spm) or None.
    """
    if len(fwd) < _MIN_FOOT_SAMPLES:
        return None
    span = float(np.percentile(fwd, 95) - np.percentile(fwd, 5))
    if span <= 1e-6:
        return None

    period = _autocorr_period(fwd, video_fps)
    if period is None:
        return None

    # One contact per stride: spacing a bit under the full period.
    distance = max(4, int(period * 0.6))
    peaks, _ = find_peaks(fwd, distance=distance, prominence=span * 0.15)
    if len(peaks) < 2:
        return None

    peak_frames = frames[peaks]
    intervals = np.diff(peak_frames)
    if intervals.mean() <= 0:
        return None
    per_leg_cadence = 60.0 / (float(np.median(intervals)) / video_fps)
    return [int(f) for f in peak_frames], per_leg_cadence


def _foot_vertical_by_frame(
    frame_angles: list[FrameAngles],
    foot_idx: int,
) -> dict[int, float]:
    """World-y (vertical, y-down) of one foot landmark, keyed by frame."""
    out: dict[int, float] = {}
    for fa in frame_angles:
        if fa.landmarks is None:
            continue
        foot = fa.landmarks.get(foot_idx)
        if foot is not None:
            out[fa.frame_number] = foot[1]
    return out


def _refine_contacts(
    contact_frames: list[int],
    foot_y_by_frame: dict[int, float],
    per_leg_cadence: float,
    video_fps: float,
    method: str,
) -> list[int]:
    """Shift forward-reach peaks forward to the true plant per ``method``.

    Both alternatives only ever move a contact *forward*, snapped onto an
    actually-analyzed frame, so downstream phase sampling always lands on a
    real frame.  ``forward_peak`` (and any unknown method) is a no-op.
    """
    if method == "forward_peak" or not foot_y_by_frame:
        return contact_frames

    sorted_frames = sorted(foot_y_by_frame)
    refined: list[int] = []

    if method == "forward_peak_delayed":
        offset = max(1, int(round(video_fps * _CONTACT_DELAY_SEC)))
        for fc in contact_frames:
            lo = bisect.bisect_left(sorted_frames, fc)
            hi = bisect.bisect_right(sorted_frames, fc + offset)
            window = sorted_frames[lo:hi]
            refined.append(window[-1] if window else fc)

    elif method == "foot_plant":
        period = video_fps * 60.0 / per_leg_cadence if per_leg_cadence > 0 else video_fps
        w = max(2, min(int(period * 0.4), int(video_fps * _PLANT_WINDOW_SEC)))
        for fc in contact_frames:
            lo = bisect.bisect_left(sorted_frames, fc)
            hi = bisect.bisect_right(sorted_frames, fc + w)
            window = sorted_frames[lo:hi]
            refined.append(
                max(window, key=lambda f: foot_y_by_frame[f]) if window else fc
            )

    else:
        return contact_frames

    # Keep events strictly ordered; collisions collapse harmlessly.
    return sorted(set(refined))


def _detect_contacts_for_side(
    frame_angles: list[FrameAngles],
    side: str,
    video_fps: float,
    contact_method: str = DEFAULT_CONTACT_METHOD,
) -> tuple[list[int], float] | None:
    """Forward-position contact detection; toe (foot_index) then heel.

    When ``contact_method`` is not ``forward_peak`` the detected peaks are
    refined toward the actual plant using the same foot landmark.
    """
    direction = _running_direction(frame_angles)
    hip_idx = _HIP_IDX[side]
    for foot_idx in (_FOOT_IDX[side], _HEEL_IDX[side]):
        frames, fwd = _forward_series(frame_angles, foot_idx, hip_idx, direction)
        result = _detect_contacts_forward(frames, fwd, video_fps)
        if result is not None:
            contact_frames, per_leg_cadence = result
            if contact_method != "forward_peak":
                foot_y = _foot_vertical_by_frame(frame_angles, foot_idx)
                contact_frames = _refine_contacts(
                    contact_frames, foot_y, per_leg_cadence, video_fps, contact_method,
                )
            return contact_frames, per_leg_cadence
    return None


# ── toe-off detection (derivative-based) ───────────────────────────────

def _detect_toe_off_derivative(
    hip_vals: np.ndarray,
    hip_segment_idx: list[int],
) -> int | None:
    """First positive zero-crossing of hip-flexion derivative (ext→flex)."""
    if len(hip_segment_idx) < 3:
        return None

    local_vals = hip_vals[hip_segment_idx]
    deriv = np.gradient(local_vals)
    sign_changes = np.where(np.diff(np.sign(deriv)) > 0)[0]

    if len(sign_changes) > 0:
        return hip_segment_idx[sign_changes[0]]
    return hip_segment_idx[int(np.argmin(local_vals))]


# ── public API ─────────────────────────────────────────────────────────

def detect_strides(
    frame_angles: list[FrameAngles],
    video_fps: float,
    *,
    side: str = "left",
    contact_method: str = DEFAULT_CONTACT_METHOD,
) -> tuple[list[StrideEvent], StrideSummary | None]:
    """Detect stride phases for one leg from foot-vertical-position contacts.

    Parameters
    ----------
    contact_method : str
        Initial-contact placement strategy — one of ``CONTACT_METHODS``.
        See the module docstring.

    Returns
    -------
    events : list[StrideEvent]
        initial_contact / mid_stance / toe_off in chronological order.
    summary : StrideSummary | None
        ``cadence_spm`` is reported as **total** cadence (≈ per-leg × 2);
        the pipeline reconciles the two legs afterwards.
    """
    contacts = _detect_contacts_for_side(
        frame_angles, side, video_fps, contact_method,
    )
    if contacts is None:
        return [], None

    contact_frames, per_leg_cadence = contacts
    if len(contact_frames) < 2:
        return [], None

    # Frame-number → timestamp lookup
    ts_by_frame = {fa.frame_number: fa.timestamp_ms for fa in frame_angles}

    events: list[StrideEvent] = []
    for fn in contact_frames:
        events.append(StrideEvent(
            phase="initial_contact",
            side=side,
            frame_number=fn,
            timestamp_ms=ts_by_frame.get(fn, 0),
        ))

    # ── mid-stance + toe-off between consecutive contacts ──────────────
    ankle_key = f"{side}_ankle_dorsiflexion"
    hip_key = f"{side}_hip_flexion"

    _, _, ankle_vals = _extract_series(frame_angles, ankle_key)
    _, _, hip_vals = _extract_series(frame_angles, hip_key)

    ankle_frame_map: dict[int, int] = {}
    for fa in frame_angles:
        if ankle_key in fa.angles:
            ankle_frame_map[fa.frame_number] = len(ankle_frame_map)
    hip_frame_map: dict[int, int] = {}
    for fa in frame_angles:
        if hip_key in fa.angles:
            hip_frame_map[fa.frame_number] = len(hip_frame_map)

    for i in range(len(contact_frames) - 1):
        start_frame = contact_frames[i]
        end_frame = contact_frames[i + 1]

        # Mid-stance: min ankle dorsiflexion between contacts
        ankle_seg = [
            ankle_frame_map[fn]
            for fn in range(start_frame, end_frame + 1)
            if fn in ankle_frame_map
        ]
        if ankle_seg:
            best_local = ankle_seg[int(np.argmin(ankle_vals[ankle_seg]))]
            fn = _series_idx_to_frame(frame_angles, ankle_key, best_local)
            events.append(StrideEvent(
                phase="mid_stance",
                side=side,
                frame_number=fn,
                timestamp_ms=ts_by_frame.get(fn, 0),
            ))

        # Toe-off: derivative zero-crossing of hip flexion
        hip_seg = [
            hip_frame_map[fn]
            for fn in range(start_frame, end_frame + 1)
            if fn in hip_frame_map
        ]
        if hip_seg:
            best_local = _detect_toe_off_derivative(hip_vals, hip_seg)
            if best_local is not None:
                fn = _series_idx_to_frame(frame_angles, hip_key, best_local)
                events.append(StrideEvent(
                    phase="toe_off",
                    side=side,
                    frame_number=fn,
                    timestamp_ms=ts_by_frame.get(fn, 0),
                ))

    events.sort(key=lambda e: e.frame_number)

    # Total cadence ≈ per-leg × 2 (matches the total-cadence threshold).
    total_cadence = round(per_leg_cadence * 2.0, 1)
    num_contacts = len(contact_frames)

    summary = StrideSummary(
        side=side,
        num_contacts=num_contacts,
        num_strides=max(0, num_contacts - 1),
        cadence_spm=total_cadence,
        cadence_rating=_rate_cadence(total_cadence),
    )

    return events, summary


_CADENCE_AGREEMENT_TOL = 0.15  # legs must agree within 15% to flag cadence


def reconcile_cadence(
    summaries: list[StrideSummary],
) -> tuple[float, bool]:
    """Reconcile per-leg total-cadence estimates into one total cadence.

    Both legs share one true cadence.  If the two estimates agree within
    ``_CADENCE_AGREEMENT_TOL`` they are averaged and treated as confident;
    otherwise we trust the side with more detected strides but mark the
    result low-confidence (the cadence flag is suppressed downstream).
    Mutates each summary's ``cadence_spm``/``cadence_rating`` so all
    consumers see one number.

    Returns
    -------
    (reconciled_total_cadence, confident)
    """
    valid = [s for s in summaries if s.cadence_spm > 0]
    if not valid:
        return 0.0, False

    if len(valid) == 1:
        reconciled = valid[0].cadence_spm
        confident = False  # one leg only — can't cross-check
    else:
        a, b = valid[0].cadence_spm, valid[1].cadence_spm
        hi = max(a, b)
        confident = hi > 0 and abs(a - b) / hi <= _CADENCE_AGREEMENT_TOL
        if confident:
            reconciled = (a + b) / 2.0
        else:
            reconciled = max(valid, key=lambda s: s.num_strides).cadence_spm

    reconciled = round(reconciled, 1)
    rating = _rate_cadence(reconciled)
    for s in summaries:
        s.cadence_spm = reconciled
        s.cadence_rating = rating
    return reconciled, confident


# ── helpers ────────────────────────────────────────────────────────────

def _rate_cadence(spm: float) -> str:
    from analysis.thresholds import score_angle
    return score_angle("cadence_spm", spm)


def _series_idx_to_frame(
    frame_angles: list[FrameAngles],
    angle_key: str,
    series_idx: int,
) -> int:
    """Map an index into an angle series back to its frame number."""
    count = 0
    for fa in frame_angles:
        if angle_key in fa.angles:
            if count == series_idx:
                return fa.frame_number
            count += 1
    return frame_angles[-1].frame_number
