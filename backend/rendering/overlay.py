"""Skeleton overlay drawing for video frames.

Supports two rendering modes:
- **Simple**: skeleton + angle labels when no lookups provided
- **Rich** (batch pipeline): color-coded skeleton segments, phase-contextual
  hero angle, problem banners with fade-in/fade-out, gait phase indicator bar
"""

from __future__ import annotations

import cv2
import numpy as np

from analysis.thresholds import score_angle
from pose.landmarks import POSE_CONNECTIONS
from rendering.phase_lookup import PhaseInfo, ProblemDisplay
from schemas.angles import AngleResult


# ── Clean skeleton: 16 joints + head ───────────────────────────────────

_CLEAN_JOINTS = frozenset(
    {11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32}
)
_HEAD_EARS = (7, 8)

# ── Segment → angle mapping for color-coding ───────────────────────────

_SEGMENT_ANGLE: dict[tuple[int, int], str] = {
    # Knee flexion
    (23, 25): "left_knee_flexion",
    (25, 27): "left_knee_flexion",
    (24, 26): "right_knee_flexion",
    (26, 28): "right_knee_flexion",
    # Hip flexion
    (11, 23): "left_hip_flexion",
    (12, 24): "right_hip_flexion",
    # Arm drive
    (11, 13): "left_arm_drive",
    (13, 15): "left_arm_drive",
    (12, 14): "right_arm_drive",
    (14, 16): "right_arm_drive",
    # Ankle dorsiflexion
    (27, 29): "left_ankle_dorsiflexion",
    (27, 31): "left_ankle_dorsiflexion",
    (29, 31): "left_ankle_dorsiflexion",
    (28, 30): "right_ankle_dorsiflexion",
    (28, 32): "right_ankle_dorsiflexion",
    (30, 32): "right_ankle_dorsiflexion",
    # Trunk lean
    (11, 12): "trunk_lean",
    (23, 24): "trunk_lean",
}

# Angles without a trustworthy reference range — segments drawn gray.
_NO_REFERENCE_ANGLES: frozenset[str] = frozenset({
    "ankle_dorsiflexion", "arm_swing", "arm_drive",
})

# ── BGR colour palettes ────────────────────────────────────────────────

_SCORE_BGR: dict[str, tuple[int, int, int]] = {
    "optimal": (80, 175, 76),     # #4CAF50
    "warning": (7, 193, 255),     # #FFC107
    "poor":    (54, 67, 244),     # #F44336
}
_NO_DATA_BGR    = (158, 158, 158)  # #9E9E9E
_SIMPLE_SKL_BGR = (200, 200, 200)
_JOINT_BGR      = (255, 255, 255)
_JOINT_RIM_BGR  = (80, 80, 80)
_HEAD_BGR       = (200, 200, 200)
_TEXT_BGR        = (230, 230, 230)
_TEXT_DIM_BGR    = (160, 160, 160)
_SHADOW_BGR      = (0, 0, 0)

_PHASE_BGR: dict[str, tuple[int, int, int]] = {
    "initial_contact": (243, 150, 33),   # #2196F3
    "mid_stance":      (80, 175, 76),    # #4CAF50
    "toe_off":         (0, 152, 255),    # #FF9800
    "swing":           (117, 117, 117),  # #757575
}

_SEVERITY_BGR: dict[str, tuple[int, int, int]] = {
    "severe":   (54, 67, 244),
    "moderate": (0, 120, 255),
    "mild":     (7, 193, 255),
}

# ── Phase → hero angle mapping ─────────────────────────────────────────

_PHASE_HERO: dict[str, str] = {
    "initial_contact": "knee_flexion",
    "mid_stance":      "ankle_dorsiflexion",
    "toe_off":         "hip_flexion",
}

# ── Problem anchor landmarks ───────────────────────────────────────────

_PROBLEM_ANCHOR: dict[str, dict[str | None, int]] = {
    "overstriding":               {"left": 27, "right": 28},
    "heel_strike":                {"left": 29, "right": 30},
    "excessive_trunk_lean":       {"left": 11, "right": 12, None: 11},
    "insufficient_trunk_lean":    {"left": 11, "right": 12, None: 11},
    "trunk_instability":          {"left": 11, "right": 12, None: 11},
    "insufficient_hip_extension": {"left": 23, "right": 24},
    "vertical_oscillation":       {"left": 23, "right": 24, None: 23},
}


# ── public API ──────────────────────────────────────────────────────────

def draw_overlay(
    frame: np.ndarray,
    norm_landmarks: list,
    angles: dict[str, AngleResult],
    *,
    visibility_threshold: float = 0.3,
    speed_band: str = "moderate",
    frame_number: int = 0,
    phase_info: dict[str, PhaseInfo] | None = None,
    active_problems: list[ProblemDisplay] | None = None,
) -> np.ndarray:
    """Draw skeleton + annotations onto *frame* (in-place) and return it.

    When *phase_info* is provided (batch pipeline), draws the rich overlay
    with color-coded segments, phase bar, hero angle, and problem banners.
    Otherwise draws a simple skeleton with angle labels (live session).
    """
    h, w = frame.shape[:2]
    rich = phase_info is not None

    # 1. Skeleton
    if rich:
        seg_colors = _build_segment_colors(angles, speed_band)
        _draw_colored_skeleton(frame, norm_landmarks, seg_colors, h, w, visibility_threshold)
    else:
        _draw_simple_skeleton(frame, norm_landmarks, h, w, visibility_threshold)

    # 2. Head indicator
    _draw_head(frame, norm_landmarks, h, w, visibility_threshold)

    # 3. Joint markers
    _draw_joints(frame, norm_landmarks, h, w, visibility_threshold)

    # 4. Angle labels
    if rich and phase_info:
        _draw_hero_angle(frame, angles, phase_info, speed_band, h, w)
        _draw_compact_angles(frame, angles, phase_info, h, w)
    else:
        _draw_all_angles(frame, angles, h, w)

    # 5. Problem banners
    if active_problems:
        _draw_problem_banners(frame, norm_landmarks, active_problems, h, w, visibility_threshold)

    # 6. Phase indicator bar
    if phase_info:
        _draw_phase_bar(frame, phase_info, h, w)

    return frame


# ── skeleton drawing ────────────────────────────────────────────────────

def _build_segment_colors(
    angles: dict[str, AngleResult],
    speed_band: str,
) -> dict[tuple[int, int], tuple[int, int, int]]:
    """Map each bone connection to a BGR colour based on angle quality.

    Ankle and arm angles have no trustworthy reference range (data-only),
    so their segments are always drawn gray rather than scored green/red.
    """
    colors: dict[tuple[int, int], tuple[int, int, int]] = {}
    for conn, angle_name in _SEGMENT_ANGLE.items():
        base = angle_name[len("left_"):] if angle_name.startswith("left_") else \
            angle_name[len("right_"):] if angle_name.startswith("right_") else angle_name
        if base in _NO_REFERENCE_ANGLES:
            colors[conn] = _NO_DATA_BGR
        elif angle_name in angles:
            rating = score_angle(angle_name, angles[angle_name].value_deg, speed_band)
            colors[conn] = _SCORE_BGR.get(rating, _NO_DATA_BGR)
        else:
            colors[conn] = _NO_DATA_BGR
    return colors


def _draw_colored_skeleton(frame, norm_landmarks, seg_colors, h, w, vis_thresh):
    for a_idx, b_idx in POSE_CONNECTIONS:
        if a_idx >= len(norm_landmarks) or b_idx >= len(norm_landmarks):
            continue
        lm_a, lm_b = norm_landmarks[a_idx], norm_landmarks[b_idx]
        if lm_a.visibility < vis_thresh or lm_b.visibility < vis_thresh:
            continue
        pt_a = (int(lm_a.x * w), int(lm_a.y * h))
        pt_b = (int(lm_b.x * w), int(lm_b.y * h))
        key = (min(a_idx, b_idx), max(a_idx, b_idx))
        colour = seg_colors.get(key, _NO_DATA_BGR)
        cv2.line(frame, pt_a, pt_b, colour, 3, cv2.LINE_AA)


def _draw_simple_skeleton(frame, norm_landmarks, h, w, vis_thresh):
    for a_idx, b_idx in POSE_CONNECTIONS:
        if a_idx >= len(norm_landmarks) or b_idx >= len(norm_landmarks):
            continue
        lm_a, lm_b = norm_landmarks[a_idx], norm_landmarks[b_idx]
        if lm_a.visibility < vis_thresh or lm_b.visibility < vis_thresh:
            continue
        pt_a = (int(lm_a.x * w), int(lm_a.y * h))
        pt_b = (int(lm_b.x * w), int(lm_b.y * h))
        cv2.line(frame, pt_a, pt_b, _SIMPLE_SKL_BGR, 2, cv2.LINE_AA)


def _draw_head(frame, norm_landmarks, h, w, vis_thresh):
    """Single filled circle at midpoint of ears — not connected to skeleton."""
    l_idx, r_idx = _HEAD_EARS
    if l_idx >= len(norm_landmarks) or r_idx >= len(norm_landmarks):
        return
    l_ear, r_ear = norm_landmarks[l_idx], norm_landmarks[r_idx]
    l_vis = l_ear.visibility >= vis_thresh
    r_vis = r_ear.visibility >= vis_thresh
    if not l_vis and not r_vis:
        return
    if l_vis and r_vis:
        mx, my = (l_ear.x + r_ear.x) / 2, (l_ear.y + r_ear.y) / 2
    elif l_vis:
        mx, my = l_ear.x, l_ear.y
    else:
        mx, my = r_ear.x, r_ear.y
    center = (int(mx * w), int(my * h))
    cv2.circle(frame, center, 12, _HEAD_BGR, -1, cv2.LINE_AA)
    cv2.circle(frame, center, 12, _JOINT_RIM_BGR, 1, cv2.LINE_AA)


def _draw_joints(frame, norm_landmarks, h, w, vis_thresh):
    for idx in _CLEAN_JOINTS:
        if idx >= len(norm_landmarks):
            continue
        lm = norm_landmarks[idx]
        if lm.visibility < vis_thresh:
            continue
        pt = (int(lm.x * w), int(lm.y * h))
        cv2.circle(frame, pt, 4, _JOINT_BGR, -1, cv2.LINE_AA)
        cv2.circle(frame, pt, 4, _JOINT_RIM_BGR, 1, cv2.LINE_AA)


# ── angle display (rich mode) ──────────────────────────────────────────

def _active_phase(phase_info: dict[str, PhaseInfo]) -> str | None:
    """Pick the most relevant gait phase for hero angle display.

    Prefers contact/stance phases over swing.
    """
    for pref in ("initial_contact", "mid_stance", "toe_off"):
        for info in phase_info.values():
            if info.phase == pref:
                return pref
    return None


def _draw_hero_angle(frame, angles, phase_info, speed_band, h, w):
    """Draw the phase-relevant angle prominently with a colored background."""
    phase = _active_phase(phase_info)
    if phase is None:
        return

    hero_base = _PHASE_HERO.get(phase)
    if hero_base is None:
        return

    # Find the side that's in this phase
    hero_side = None
    for side, info in phase_info.items():
        if info.phase == phase:
            hero_side = side
            break

    hero_key = f"{hero_side}_{hero_base}" if hero_side else hero_base
    if hero_key not in angles:
        for key in angles:
            if hero_base in key:
                hero_key = key
                break
        else:
            return

    result = angles[hero_key]
    # Ankle/arm angles have no trustworthy reference — show the value with a
    # neutral background rather than scoring it red/green.
    if hero_base in _NO_REFERENCE_ANGLES:
        bg_colour = _NO_DATA_BGR
    else:
        rating = score_angle(hero_key, result.value_deg, speed_band)
        bg_colour = _SCORE_BGR.get(rating, _NO_DATA_BGR)

    display = hero_base.replace("_", " ").title()
    label = f"{display}: {result.value_deg:.1f}\xb0"
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.70
    thickness = 2
    (tw, th), baseline = cv2.getTextSize(label, font, scale, thickness)

    x, y = 15, h - 60
    pad = 8

    _draw_alpha_rect(
        frame,
        (x - pad, y - th - pad),
        (x + tw + pad, y + pad + baseline),
        bg_colour,
        0.7,
    )
    cv2.putText(frame, label, (x, y), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)

    phase_label = phase.replace("_", " ").title()
    cv2.putText(
        frame, phase_label, (x, y + th + 8),
        font, 0.35, _TEXT_DIM_BGR, 1, cv2.LINE_AA,
    )


def _draw_compact_angles(frame, angles, phase_info, h, w):
    """Draw non-hero angles smaller and dimmer in side columns."""
    phase = _active_phase(phase_info)
    hero_base = _PHASE_HERO.get(phase, "") if phase else ""

    font = cv2.FONT_HERSHEY_SIMPLEX

    # Trunk lean always visible (small, top center)
    if "trunk_lean" in angles:
        tl = angles["trunk_lean"]
        label = f"Trunk Lean: {tl.value_deg:.1f}\xb0"
        (tw, _), _ = cv2.getTextSize(label, font, 0.40, 1)
        x = (w - tw) // 2
        cv2.putText(frame, label, (x, 20), font, 0.40, _SHADOW_BGR, 3, cv2.LINE_AA)
        cv2.putText(frame, label, (x, 20), font, 0.40, _TEXT_BGR, 1, cv2.LINE_AA)

    # Left column (dim, skip hero angle)
    y = 40
    for name, result in angles.items():
        if not name.startswith("left_"):
            continue
        base = name.removeprefix("left_")
        if base == hero_base:
            continue
        label = f"L {base}: {result.value_deg:.1f}\xb0"
        cv2.putText(frame, label, (10, y), font, 0.36, _SHADOW_BGR, 2, cv2.LINE_AA)
        cv2.putText(frame, label, (10, y), font, 0.36, _TEXT_DIM_BGR, 1, cv2.LINE_AA)
        y += 16

    # Right column (dim, skip hero angle)
    y = 40
    for name, result in angles.items():
        if not name.startswith("right_"):
            continue
        base = name.removeprefix("right_")
        if base == hero_base:
            continue
        label = f"R {base}: {result.value_deg:.1f}\xb0"
        (tw, _), _ = cv2.getTextSize(label, font, 0.36, 1)
        cv2.putText(frame, label, (w - tw - 10, y), font, 0.36, _SHADOW_BGR, 2, cv2.LINE_AA)
        cv2.putText(frame, label, (w - tw - 10, y), font, 0.36, _TEXT_DIM_BGR, 1, cv2.LINE_AA)
        y += 16


# ── angle display (simple / live mode) ─────────────────────────────────

def _draw_all_angles(frame, angles, h, w):
    """Angle display for live session (no phase context)."""
    font = cv2.FONT_HERSHEY_SIMPLEX

    # Midline angles centred at top
    for name, result in angles.items():
        if name.startswith("left_") or name.startswith("right_"):
            continue
        label = f"{name.replace('_', ' ').title()}: {result.value_deg:.1f}\xb0"
        (tw, _), _ = cv2.getTextSize(label, font, 0.45, 1)
        x = (w - tw) // 2
        cv2.putText(frame, label, (x, 24), font, 0.45, _SHADOW_BGR, 3, cv2.LINE_AA)
        cv2.putText(frame, label, (x, 24), font, 0.45, _TEXT_BGR, 1, cv2.LINE_AA)

    # Left column
    y = 24
    for name, result in angles.items():
        if not name.startswith("left_"):
            continue
        label = f"L {name.removeprefix('left_')}: {result.value_deg:.1f}\xb0"
        cv2.putText(frame, label, (10, y), font, 0.45, _SHADOW_BGR, 3, cv2.LINE_AA)
        cv2.putText(frame, label, (10, y), font, 0.45, _TEXT_BGR, 1, cv2.LINE_AA)
        y += 18

    # Right column
    y = 24
    for name, result in angles.items():
        if not name.startswith("right_"):
            continue
        label = f"R {name.removeprefix('right_')}: {result.value_deg:.1f}\xb0"
        (tw, _), _ = cv2.getTextSize(label, font, 0.45, 1)
        cv2.putText(frame, label, (w - tw - 10, y), font, 0.45, _SHADOW_BGR, 3, cv2.LINE_AA)
        cv2.putText(frame, label, (w - tw - 10, y), font, 0.45, _TEXT_BGR, 1, cv2.LINE_AA)
        y += 18


# ── problem banners ─────────────────────────────────────────────────────

def _draw_problem_banners(frame, norm_landmarks, problems, h, w, vis_thresh):
    """Draw coloured labels near the relevant body part with alpha fading."""
    drawn: list[tuple[int, int]] = []

    for prob in problems:
        colour = _SEVERITY_BGR.get(prob.severity, (0, 120, 255))
        alpha = prob.alpha

        # Find anchor landmark
        anchor_map = _PROBLEM_ANCHOR.get(prob.problem_id)
        anchor_idx = None
        if anchor_map:
            anchor_idx = anchor_map.get(prob.side) or anchor_map.get(None)

        if anchor_idx is not None and anchor_idx < len(norm_landmarks):
            lm = norm_landmarks[anchor_idx]
            if lm.visibility >= vis_thresh:
                px = int(lm.x * w)
                py = int(lm.y * h) - 15

                for dx, dy in drawn:
                    if abs(px - dx) < 80 and abs(py - dy) < 20:
                        py -= 22

                label = prob.display_name.upper()
                font = cv2.FONT_HERSHEY_SIMPLEX
                (tw, th), _ = cv2.getTextSize(label, font, 0.40, 1)
                pad = 4

                _draw_alpha_rect(
                    frame,
                    (px - pad, py - th - pad),
                    (px + tw + pad, py + pad),
                    colour,
                    alpha * 0.8,
                )
                t_a = max(0, min(255, int(255 * alpha)))
                cv2.putText(
                    frame, label, (px, py),
                    font, 0.40, (t_a, t_a, t_a), 1, cv2.LINE_AA,
                )
                drawn.append((px, py))
                continue

        # Fallback: bottom-left
        y_pos = h - 40 - len(drawn) * 22
        label = f"  {prob.display_name.upper()}  "
        font = cv2.FONT_HERSHEY_SIMPLEX
        (tw, th), _ = cv2.getTextSize(label, font, 0.45, 1)
        _draw_alpha_rect(
            frame, (8, y_pos - th - 4), (12 + tw, y_pos + 4), colour, alpha * 0.8,
        )
        t_a = max(0, min(255, int(255 * alpha)))
        cv2.putText(
            frame, label, (10, y_pos),
            font, 0.45, (t_a, t_a, t_a), 1, cv2.LINE_AA,
        )
        drawn.append((10, y_pos))


# ── phase indicator bar ─────────────────────────────────────────────────

def _draw_phase_bar(frame, phase_info, h, w):
    """Thin horizontal bars at the bottom showing current gait phase per side."""
    bar_h = 10
    sides = sorted(phase_info.keys())

    for i, side in enumerate(sides):
        info = phase_info[side]
        y_top = h - bar_h * (len(sides) - i) - 2
        colour = _PHASE_BGR.get(info.phase, (117, 117, 117))

        _draw_alpha_rect(frame, (0, y_top), (w, y_top + bar_h), colour, 0.85)

        phase_label = f"{side[0].upper()}: {info.phase.replace('_', ' ')}"
        cv2.putText(
            frame, phase_label, (5, y_top + bar_h - 2),
            cv2.FONT_HERSHEY_SIMPLEX, 0.30, (255, 255, 255), 1, cv2.LINE_AA,
        )

        stride_label = f"Stride {info.stride_num}/{info.total_strides} ({side[0].upper()})"
        (tw, _), _ = cv2.getTextSize(
            stride_label, cv2.FONT_HERSHEY_SIMPLEX, 0.30, 1,
        )
        cv2.putText(
            frame, stride_label, (w - tw - 5, y_top + bar_h - 2),
            cv2.FONT_HERSHEY_SIMPLEX, 0.30, (255, 255, 255), 1, cv2.LINE_AA,
        )


# ── utility ─────────────────────────────────────────────────────────────

def _draw_alpha_rect(frame, pt1, pt2, colour, alpha):
    """Draw a filled rectangle with alpha blending on a sub-region."""
    x1 = max(0, int(pt1[0]))
    y1 = max(0, int(pt1[1]))
    x2 = min(frame.shape[1], int(pt2[0]))
    y2 = min(frame.shape[0], int(pt2[1]))
    if x1 >= x2 or y1 >= y2:
        return
    sub = frame[y1:y2, x1:x2]
    rect = np.full_like(sub, colour, dtype=np.uint8)
    blended = cv2.addWeighted(rect, alpha, sub, 1.0 - alpha, 0)
    frame[y1:y2, x1:x2] = blended
