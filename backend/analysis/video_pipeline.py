"""Batch video analysis pipeline (two-pass).

Pass 1 (analysis): Run MediaPipe, compute angles, detect strides, run form
analysis. Stores per-frame landmark data needed by the render pass.

Pass 2 (rendering): Re-read the source video and draw a rich overlay using
the complete analysis results — phase bar, color-coded skeleton, hero angle,
problem banners with fade — that depends on forward-looking information.

The source video is read twice rather than buffering all frames in memory.
For typical inputs this is faster (no GC pressure) and avoids OOM on long
videos.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from analysis.angles import AngleCalculator
from analysis.stride_detector import DEFAULT_CONTACT_METHOD
from analysis.thresholds import get_threshold
from pose.detector import PoseDetector
from pose.landmarks import LandmarkProcessor
from pose.smoothing import SavitzkyGolayBuffer
from rendering.overlay import draw_overlay
from rendering.phase_lookup import build_phase_lookup, build_problem_lookup
from schemas.analyze import AngleSummary, FormAnalysis, FrameAngles, StrideEvent, StrideSummary
from schemas.angles import AngleResult


logger = logging.getLogger("pacevision.pipeline")

_MAX_CONSECUTIVE_MISSES = 120


class _NormLandmark:
    """Lightweight stand-in for a MediaPipe NormalizedLandmark.

    The render pass stores normalized landmarks in a dict and replays them
    onto the source frames; the overlay only needs ``.x``, ``.y``, and
    ``.visibility``.
    """

    __slots__ = ("x", "y", "visibility")

    def __init__(self, x: float, y: float, visibility: float) -> None:
        self.x = x
        self.y = y
        self.visibility = visibility


class VideoPipeline:
    """Two-pass batch processor: video file in → annotated video + data out.

    Parameters
    ----------
    skip_frames : int
        Process every *skip_frames*-th frame in the analysis pass.
        ``1`` = analyze every frame.
    detection_height : int | None
        If set, resize frames to this height for MediaPipe detection.
        ``None`` = use original resolution.
    progress_callback : callable | None
        Called with ``(frames_done, total_frames)``. Progress spans both
        passes: 0–50% during analysis, 50–100% during rendering.
    """

    def __init__(
        self,
        *,
        skip_frames: int = 1,
        detection_height: int | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> None:
        if skip_frames < 1:
            raise ValueError("skip_frames must be >= 1")

        self._skip = skip_frames
        self._det_height = detection_height
        self._progress_cb = progress_callback

        self._detector: PoseDetector | None = None
        self._smoother: SavitzkyGolayBuffer | None = None
        self._angle_calc = AngleCalculator()

    # ── public API ────────────────────────────────────────────────────

    def run(
        self,
        input_path: str | Path,
        output_path: str | Path,
    ) -> tuple[
        list[FrameAngles], float, int, int, float,
        list[StrideEvent], list[StrideSummary], FormAnalysis,
    ]:
        """Process the video and return results.

        Returns
        -------
        tuple of:
            frame_angles : list[FrameAngles]
            duration_sec : float   — wall-clock processing time (both passes)
            total_frames : int     — frames in the source video
            analyzed_frames : int  — frames that got full detection
            video_fps : float      — source video FPS
            stride_events : list[StrideEvent]
            stride_summaries : list[StrideSummary]
            form_analysis : FormAnalysis
        """
        input_path = str(input_path)
        output_path = str(output_path)

        t_start = time.perf_counter()

        # ── Pass 1: analysis ──
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {input_path}")
        try:
            (
                frame_angles, total_frames, analyzed, video_fps, width, height,
                norm_lm_by_frame,
            ) = self._analyze(cap)
        finally:
            cap.release()

        stride_events, stride_summaries, form_analysis = analyze_strides_and_form(
            frame_angles, video_fps,
        )

        # ── Pass 2: rendering ──
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise ValueError(f"Cannot open video for render pass: {input_path}")
        try:
            self._render(
                cap, output_path,
                width, height, video_fps, total_frames,
                frame_angles, norm_lm_by_frame,
                stride_events, form_analysis,
            )
        finally:
            cap.release()

        duration = time.perf_counter() - t_start
        return (
            frame_angles, duration, total_frames, analyzed, video_fps,
            stride_events, stride_summaries, form_analysis,
        )

    # ── pass 1: analysis ──────────────────────────────────────────────

    def _analyze(
        self,
        cap: cv2.VideoCapture,
    ) -> tuple[
        list[FrameAngles], int, int, float, int, int,
        dict[int, list[_NormLandmark]],
    ]:
        """Detect pose + compute angles for every (sampled) frame.

        Returns the per-frame angle records plus a snapshot of normalized
        landmarks keyed by frame number for the render pass.
        """
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        if total_frames <= 0 or width <= 0 or height <= 0:
            raise ValueError("Invalid video file: cannot read dimensions or frame count")

        det_scale: float | None = None
        if self._det_height and self._det_height < height:
            det_scale = self._det_height / height

        self._detector = PoseDetector()
        self._smoother = SavitzkyGolayBuffer()

        frame_angles: list[FrameAngles] = []
        norm_lm_by_frame: dict[int, list[_NormLandmark]] = {}
        analyzed_count = 0
        consecutive_misses = 0
        last_norm_landmarks: list[_NormLandmark] | None = None
        frame_idx = 0

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                timestamp_ms = int(cap.get(cv2.CAP_PROP_POS_MSEC))
                should_detect = (frame_idx % self._skip == 0)

                if should_detect and consecutive_misses < _MAX_CONSECUTIVE_MISSES:
                    det_frame = frame
                    if det_scale is not None:
                        det_frame = cv2.resize(
                            frame, None, fx=det_scale, fy=det_scale,
                            interpolation=cv2.INTER_AREA,
                        )

                    result = self._detector.detect(det_frame)

                    if result is not None:
                        consecutive_misses = 0
                        raw = LandmarkProcessor.extract_world_landmarks(
                            result.pose_world_landmarks[0],
                        )
                        smoothed = self._smoother.push(raw)
                        angles = self._angle_calc.compute_all(smoothed)
                        analyzed_count += 1

                        if result.pose_landmarks:
                            # Snapshot normalised landmarks (the MediaPipe
                            # object is reused across frames — we copy the
                            # primitive values we need).
                            last_norm_landmarks = [
                                _NormLandmark(
                                    lm.x, lm.y,
                                    getattr(lm, "visibility", 1.0),
                                )
                                for lm in result.pose_landmarks[0]
                            ]

                        lm_dict = {
                            lm.index: (lm.x, lm.y, lm.z)
                            for lm in smoothed
                        }

                        frame_angles.append(FrameAngles(
                            frame_number=frame_idx,
                            timestamp_ms=timestamp_ms,
                            angles=angles,
                            landmarks=lm_dict,
                        ))
                    else:
                        consecutive_misses += 1

                if last_norm_landmarks is not None:
                    norm_lm_by_frame[frame_idx] = last_norm_landmarks

                frame_idx += 1

                if self._progress_cb:
                    # Analysis pass occupies the first half of progress.
                    self._progress_cb(frame_idx // 2, total_frames)
        finally:
            self._detector.close()
            self._detector = None
            self._smoother = None

        return (
            frame_angles, total_frames, analyzed_count, video_fps,
            width, height, norm_lm_by_frame,
        )

    # ── pass 2: rendering ─────────────────────────────────────────────

    def _render(
        self,
        cap: cv2.VideoCapture,
        output_path: str,
        width: int,
        height: int,
        video_fps: float,
        total_frames: int,
        frame_angles: list[FrameAngles],
        norm_lm_by_frame: dict[int, list[_NormLandmark]],
        stride_events: list[StrideEvent],
        form_analysis: FormAnalysis,
    ) -> None:
        """Draw the rich overlay onto every frame and write the output video.

        OpenCV on Windows reliably writes only ``mp4v`` (MPEG-4 Part 2), which
        no browser can decode inline. We therefore render the overlay to a
        temporary ``mp4v`` file and transcode it to browser-playable H.264
        with the bundled ``imageio-ffmpeg`` binary (see ``_transcode_to_h264``).
        If ffmpeg is unavailable, the mp4v file is kept as a fallback so the
        clip is at least downloadable.
        """
        # Render to a sibling temp file; transcode into output_path afterwards.
        raw_path = f"{output_path}.raw.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(raw_path, fourcc, video_fps, (width, height))
        if not writer.isOpened():
            raise ValueError(f"Cannot create output video: {raw_path}")

        angles_by_frame: dict[int, dict[str, AngleResult]] = {
            fa.frame_number: fa.angles for fa in frame_angles
        }

        phase_lookup = build_phase_lookup(stride_events, total_frames)
        problem_lookup = build_problem_lookup(form_analysis.problems, total_frames)
        speed_band = form_analysis.speed_band

        last_angles: dict[str, AngleResult] = {}
        frame_idx = 0

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                if frame_idx in angles_by_frame:
                    last_angles = angles_by_frame[frame_idx]
                norm_lms = norm_lm_by_frame.get(frame_idx)

                out_frame = frame
                if norm_lms is not None:
                    out_frame = draw_overlay(
                        frame,
                        norm_lms,
                        last_angles,
                        speed_band=speed_band,
                        frame_number=frame_idx,
                        phase_info=phase_lookup.get(frame_idx),
                        active_problems=problem_lookup.get(frame_idx),
                    )

                writer.write(out_frame)
                frame_idx += 1

                if self._progress_cb:
                    # Rendering pass occupies the second half of progress.
                    self._progress_cb(
                        total_frames // 2 + frame_idx // 2,
                        total_frames,
                    )
        finally:
            writer.release()

        # Transcode the mp4v render into browser-playable H.264.
        self._transcode_to_h264(raw_path, output_path, video_fps)

    @staticmethod
    def _transcode_to_h264(raw_path: str, output_path: str, video_fps: float) -> None:
        """Transcode an mp4v render to H.264 (yuv420p) for in-browser playback.

        Uses the static ffmpeg binary bundled with ``imageio-ffmpeg`` so no
        system install is required. ``+faststart`` moves the moov atom to the
        front so the browser can begin playback before the full file loads.
        On any failure the raw mp4v file is promoted to ``output_path`` as a
        downloadable fallback.
        """
        # Prefer a real system ffmpeg (installed in the image); the bundled
        # imageio-ffmpeg binary is unreliable on slim containers. Fall back to
        # it only if no system ffmpeg is on PATH.
        ffmpeg_exe: str | None = shutil.which("ffmpeg")
        if ffmpeg_exe is None:
            try:
                import imageio_ffmpeg

                ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            except Exception as exc:  # pragma: no cover - depends on env
                logger.warning(
                    "No system ffmpeg and imageio-ffmpeg unavailable (%s); "
                    "serving mp4v render (may not play inline).", exc,
                )

        if ffmpeg_exe:
            cmd = [
                ffmpeg_exe, "-y",
                "-i", raw_path,
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "veryfast",
                "-crf", "23",
                "-r", f"{video_fps:.6f}",
                "-movflags", "+faststart",
                "-an",
                output_path,
            ]
            try:
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                if proc.returncode == 0 and os.path.exists(output_path):
                    try:
                        os.remove(raw_path)
                    except OSError:
                        pass
                    return
                tail = proc.stderr.decode("utf-8", "replace")[-600:]
                logger.warning(
                    "ffmpeg transcode failed (code %s): %s", proc.returncode, tail,
                )
            except Exception as exc:  # pragma: no cover - depends on env
                logger.warning("ffmpeg transcode error: %s", exc)

        # Fallback: promote the mp4v render to the expected output path.
        try:
            if os.path.exists(output_path):
                os.remove(output_path)
            shutil.move(raw_path, output_path)
        except OSError as exc:
            raise ValueError(
                f"Could not finalize output video at {output_path}: {exc}"
            ) from exc


# ── stride + form analysis (reusable across analysis & recompute) ───────

def analyze_strides_and_form(
    frame_angles: list[FrameAngles],
    video_fps: float,
    *,
    contact_method: str = DEFAULT_CONTACT_METHOD,
) -> tuple[list[StrideEvent], list[StrideSummary], FormAnalysis]:
    """Detect strides for both legs and run form analysis.

    Pure function of ``frame_angles`` (no MediaPipe), so it can be re-run
    cheaply with a different ``contact_method`` to recompute the angle
    summary/ratings without re-processing the video.
    """
    from analysis.stride_detector import detect_strides, reconcile_cadence
    from analysis.form_problems import analyze_form

    all_events: list[StrideEvent] = []
    all_summaries: list[StrideSummary] = []
    for side in ("left", "right"):
        events, summary = detect_strides(
            frame_angles, video_fps, side=side, contact_method=contact_method,
        )
        all_events.extend(events)
        if summary is not None:
            all_summaries.append(summary)

    # Both legs share one true cadence — reconcile the two estimates so the
    # noisy/occluded leg can't produce a false cadence flag.  When the legs
    # disagree, cadence is reported as data but not flagged.
    _reconciled, cadence_confident = reconcile_cadence(all_summaries)

    all_events.sort(key=lambda e: e.frame_number)
    form_analysis = analyze_form(
        frame_angles, all_events, all_summaries,
        cadence_confident=cadence_confident,
    )
    return all_events, all_summaries, form_analysis


# ── phase-aware angle summary config (Phase 6) ──────────────────────────

# The gait phase at which each angle is biomechanically meaningful.
_ANGLE_PHASE: dict[str, str] = {
    "knee_flexion":       "initial_contact",
    "hip_flexion":        "max_flexion",
    "ankle_dorsiflexion": "mid_stance",
    "trunk_lean":         "continuous",
    "arm_swing":          "continuous",
    "arm_drive":          "continuous",
}

# Angles without a trustworthy optimal range — reported as data only.
_NO_REFERENCE_ANGLES: frozenset[str] = frozenset({
    "ankle_dorsiflexion", "arm_swing", "arm_drive",
})


def _base_angle_name(name: str) -> str:
    for prefix in ("left_", "right_"):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def _phase_value(
    name: str,
    base: str,
    values: list[float],
    frames: list[int],
    contact_frames_by_side: dict[str, set[int]],
) -> float | None:
    """Sample the angle at its meaningful gait phase.

    - initial_contact: mean at this side's contact frames (knee at contact)
    - max_flexion:     peak flexion = ~min geometric angle (10th percentile)
    - mid_stance:      ~min dorsiflexion (10th percentile)
    - continuous:      mean over the whole run (trunk lean, arm angles)
    """
    if not values:
        return None
    phase = _ANGLE_PHASE.get(base, "continuous")
    arr = np.array(values, dtype=np.float64)

    if phase == "initial_contact":
        side = "left" if name.startswith("left_") else "right" if name.startswith("right_") else None
        contacts = contact_frames_by_side.get(side, set()) if side else set()
        at_contact = [v for v, f in zip(values, frames) if f in contacts]
        if at_contact:
            return round(float(np.mean(at_contact)), 2)
        return round(float(np.mean(arr)), 2)
    if phase in ("max_flexion", "mid_stance"):
        # Peak flexion / dorsiflexion ≈ smallest geometric angle; use a
        # robust low percentile instead of the single-frame minimum.
        return round(float(np.percentile(arr, 10)), 2)
    return round(float(np.mean(arr)), 2)


def summarize_angles(
    frame_angles: list[FrameAngles],
    stride_events: list[StrideEvent] | None = None,
    speed_band: str = "moderate",
) -> list[AngleSummary]:
    """Aggregate per-frame angles into phase-aware summaries.

    Whole-video mean/min/max/std power the charts; ``phase_value_deg`` is
    the angle at its meaningful phase and drives the soft in/out-of-range
    rating (only for angles with a trustworthy reference).
    """
    if not frame_angles:
        return []

    # Per-side initial-contact frames for phase sampling
    contact_frames_by_side: dict[str, set[int]] = {"left": set(), "right": set()}
    for ev in (stride_events or []):
        if ev.phase == "initial_contact" and ev.side in contact_frames_by_side:
            contact_frames_by_side[ev.side].add(ev.frame_number)

    buckets: dict[str, list[float]] = {}
    frame_buckets: dict[str, list[int]] = {}
    for fa in frame_angles:
        for name, result in fa.angles.items():
            buckets.setdefault(name, []).append(result.value_deg)
            frame_buckets.setdefault(name, []).append(fa.frame_number)

    summaries: list[AngleSummary] = []
    for name, values in buckets.items():
        arr = np.array(values, dtype=np.float64)
        base = _base_angle_name(name)
        phase = _ANGLE_PHASE.get(base, "continuous")
        phase_val = _phase_value(
            name, base, values, frame_buckets[name], contact_frames_by_side,
        )

        if base in _NO_REFERENCE_ANGLES:
            lo = hi = None
            rating = "no_reference"
        else:
            lo, hi = get_threshold(name, speed_band)
            if phase_val is not None and lo <= phase_val <= hi:
                rating = "in_range"
            else:
                rating = "out_of_range"

        summaries.append(AngleSummary(
            name=name,
            mean_deg=round(float(np.mean(arr)), 2),
            min_deg=round(float(np.min(arr)), 2),
            max_deg=round(float(np.max(arr)), 2),
            std_deg=round(float(np.std(arr)), 2),
            phase=phase,
            phase_value_deg=phase_val,
            min_threshold=lo,
            max_threshold=hi,
            rating=rating,
        ))

    return summaries
