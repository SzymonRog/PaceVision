"""Precomputed lookup tables for the two-pass render pipeline.

Avoids repeated linear scans during rendering by precomputing:
1. Gait phase for each frame number (with stride count)
2. Active form problems (with fade-in/fade-out alpha) for each frame
"""

from __future__ import annotations

from dataclasses import dataclass

from schemas.analyze import FormProblem, StrideEvent


_FADE_IN_FRAMES = 5
_FADE_OUT_FRAMES = 10


@dataclass
class PhaseInfo:
    """Gait phase state at a particular frame."""

    phase: str          # "initial_contact" | "mid_stance" | "toe_off" | "swing"
    side: str           # "left" | "right"
    stride_num: int
    total_strides: int


@dataclass
class ProblemDisplay:
    """A form problem's display state at a particular frame."""

    problem_id: str
    display_name: str
    severity: str
    side: str | None
    metric_value: float
    metric_unit: str
    alpha: float        # 0.0–1.0 for fade in/out


def build_phase_lookup(
    stride_events: list[StrideEvent],
    total_frames: int,
) -> dict[int, dict[str, PhaseInfo]]:
    """Build frame_number -> {side: PhaseInfo} lookup.

    Between events the phase from the last event holds.
    After toe_off and before next initial_contact -> "swing".
    """
    if not stride_events:
        return {}

    total_strides: dict[str, int] = {}
    for ev in stride_events:
        if ev.phase == "initial_contact":
            total_strides[ev.side] = total_strides.get(ev.side, 0) + 1

    result: dict[int, dict[str, PhaseInfo]] = {}

    for side in ("left", "right"):
        side_events = sorted(
            [e for e in stride_events if e.side == side],
            key=lambda e: e.frame_number,
        )
        if not side_events:
            continue

        stride_count = 0
        ts = total_strides.get(side, 0)

        for i, ev in enumerate(side_events):
            if ev.phase == "initial_contact":
                stride_count += 1

            end_frame = (
                side_events[i + 1].frame_number
                if i + 1 < len(side_events)
                else total_frames
            )

            for f in range(ev.frame_number, end_frame):
                phase = (
                    "swing"
                    if ev.phase == "toe_off" and f > ev.frame_number
                    else ev.phase
                )
                result.setdefault(f, {})[side] = PhaseInfo(
                    phase=phase,
                    side=side,
                    stride_num=stride_count,
                    total_strides=ts,
                )

    return result


def build_problem_lookup(
    problems: list[FormProblem],
    total_frames: int,
) -> dict[int, list[ProblemDisplay]]:
    """Build frame_number -> active problems lookup with fade-in/fade-out.

    Each problem frame triggers a display window:
      [event_frame .. event_frame + FADE_IN + FADE_OUT)
    Alpha ramps 0->1 during fade-in, 1->0 during fade-out.
    Isolated-tier problems are excluded.
    """
    raw: dict[int, list[ProblemDisplay]] = {}

    for prob in problems:
        if prob.tier == "isolated":
            continue

        for event_frame in prob.frames:
            window_end = min(
                total_frames,
                event_frame + _FADE_IN_FRAMES + _FADE_OUT_FRAMES,
            )
            for f in range(max(0, event_frame), window_end):
                offset = f - event_frame
                if offset < _FADE_IN_FRAMES:
                    alpha = (offset + 1) / _FADE_IN_FRAMES
                else:
                    alpha = 1.0 - (offset - _FADE_IN_FRAMES) / _FADE_OUT_FRAMES

                raw.setdefault(f, []).append(ProblemDisplay(
                    problem_id=prob.problem_id,
                    display_name=prob.display_name,
                    severity=prob.severity,
                    side=prob.side,
                    metric_value=prob.metric_value,
                    metric_unit=prob.metric_unit,
                    alpha=max(0.0, min(1.0, alpha)),
                ))

    # Deduplicate: keep highest alpha per problem+side combination
    for f in raw:
        best: dict[str, ProblemDisplay] = {}
        for pd in raw[f]:
            key = f"{pd.problem_id}_{pd.side}"
            if key not in best or pd.alpha > best[key].alpha:
                best[key] = pd
        raw[f] = list(best.values())

    return raw
