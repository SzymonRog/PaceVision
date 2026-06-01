"""Pydantic schemas for the video analysis endpoint."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from schemas.angles import AngleResult


class JobStatus(str, Enum):
    """Lifecycle states for an analysis job."""

    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class AnalyzeVideoResponse(BaseModel):
    """Returned immediately when a video is submitted for analysis."""

    job_id: str
    status: JobStatus
    created_at: datetime


class JobProgress(BaseModel):
    """Progress update for an in-flight analysis job."""

    job_id: str
    status: JobStatus
    progress_pct: float = Field(ge=0.0, le=100.0)
    frames_processed: int = 0
    total_frames: int = 0
    error: str | None = None


class FrameAngles(BaseModel):
    """Angle results for a single frame."""

    frame_number: int
    timestamp_ms: int
    angles: dict[str, AngleResult]
    landmarks: dict[int, tuple[float, float, float]] | None = None


class AngleSummary(BaseModel):
    """Phase-aware summary for one angle (Phase 6: data-first).

    ``mean/min/max/std_deg`` describe the whole-video distribution (for
    charts).  ``phase_value_deg`` is the angle sampled at the gait phase
    where it is biomechanically meaningful (``phase``).  The optimal range
    and ``rating`` are evaluated ONLY at that phase, and only for angles
    with a trustworthy reference — ankle and arm angles are data-only
    (``rating == "no_reference"``, thresholds ``None``).
    """

    name: str
    mean_deg: float
    min_deg: float
    max_deg: float
    std_deg: float
    phase: str                          # "initial_contact" | "max_flexion" | "mid_stance" | "continuous"
    phase_value_deg: float | None = None  # representative value at that phase
    min_threshold: float | None = None  # optimal range lower bound (None = no reference)
    max_threshold: float | None = None  # optimal range upper bound (None = no reference)
    rating: str  # "in_range" | "out_of_range" | "no_reference"


class StrideEvent(BaseModel):
    """A single detected gait phase event."""

    phase: str          # "initial_contact" | "mid_stance" | "toe_off"
    side: str           # "left" | "right"
    frame_number: int
    timestamp_ms: int


class StrideSummary(BaseModel):
    """Aggregated stride metrics for one side."""

    side: str
    num_contacts: int
    num_strides: int
    cadence_spm: float       # steps per minute
    cadence_rating: str      # "optimal" | "warning" | "poor"


class FormProblem(BaseModel):
    """A detected running form problem at a specific stride phase."""

    problem_id: str           # e.g. "overstriding", "heel_strike"
    display_name: str         # e.g. "Overstriding"
    severity: str             # "mild" | "moderate" | "severe"
    confidence: float = Field(ge=0.0, le=1.0)
    side: str | None = None   # "left" | "right" | None (bilateral)
    phase: str                # stride phase where detected
    description: str          # human-readable explanation
    recommendation: str       # coaching tip
    occurrences: int          # strides showing this problem
    total_strides: int
    occurrence_pct: float     # percentage of strides affected
    frames: list[int]         # frame numbers where detected
    metric_value: float       # the measured value
    threshold: float          # the threshold exceeded
    metric_unit: str          # "meters", "degrees", "spm"
    # ── Phase 2 additions ────────────────────────────────────────────
    tier: str = "consistent"  # "consistent" | "intermittent" | "isolated"
    outlier_strides_excluded: int = 0  # strides rejected as measurement noise
    # ── Phase 5 additions ────────────────────────────────────────────
    category: str = ""                 # "impact" | "propulsion" | "upper_body" | "symmetry"
    speed_band_adjusted: bool = False  # threshold modified by speed band
    self_cal_applied: bool = False     # self-calibration filtered some strides


class FormAnalysis(BaseModel):
    """Phase-aware running form analysis results."""

    problems: list[FormProblem] = []
    strike_pattern: str = "unknown"  # "heel" | "midfoot" | "forefoot" | "mixed" | "unknown"
    asymmetry_index: dict[str, float] = {}  # angle_name -> ASI%
    # ── Phase 2 additions ────────────────────────────────────────────
    min_strides_met: bool = True    # False if <7 strides detected per side
    low_confidence_warning: str | None = None  # message when min_strides_met is False
    # ── Phase 3 additions ────────────────────────────────────────────
    speed_band: str = "moderate"    # "slow" | "moderate" | "fast"
    estimated_cadence: float = 0.0  # average cadence across both sides (SPM)


class AnalysisResult(BaseModel):
    """Full analysis result returned when a job completes."""

    job_id: str
    status: JobStatus
    duration_sec: float
    total_frames: int
    analyzed_frames: int
    video_fps: float
    frame_angles: list[FrameAngles]
    summary: list[AngleSummary]
    stride_events: list[StrideEvent] = []
    stride_summary: list[StrideSummary] = []
    form_analysis: FormAnalysis | None = None
    has_video: bool = False
