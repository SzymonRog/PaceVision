/**
 * Data model for the PaceVision analysis result.
 * Mirrors the backend `/api/analyze-video/{id}/result` payload and the
 * SSE status stream. See FRONTEND_REQUIREMENTS.md §3.
 */

export type JobStatus = "queued" | "processing" | "completed" | "failed";

export interface JobCreated {
  job_id: string;
  status: JobStatus;
  created_at: string;
}

export interface JobProgress {
  status: JobStatus;
  progress_pct: number;
  frames_processed: number;
  total_frames: number;
  error?: string | null;
}

export type AngleName =
  | "left_knee_flexion" | "right_knee_flexion"
  | "left_hip_flexion" | "right_hip_flexion"
  | "left_ankle_dorsiflexion" | "right_ankle_dorsiflexion"
  | "left_arm_swing" | "right_arm_swing"
  | "left_arm_drive" | "right_arm_drive"
  | "trunk_lean";

export interface FrameAngle {
  name: string;
  value_deg: number;
  min_threshold: number | null;
  max_threshold: number | null;
  rating: string | null;
  landmarks_used: number[];
}

export interface FrameEntry {
  frame_number: number;
  timestamp_ms: number;
  angles: Record<string, FrameAngle>;
  landmarks: Record<string, [number, number, number]>;
}

export type SummaryPhase =
  | "initial_contact" | "max_flexion" | "mid_stance" | "continuous";
export type SummaryRating = "in_range" | "out_of_range" | "no_reference";

export interface AngleSummary {
  name: string;
  mean_deg: number;
  min_deg: number;
  max_deg: number;
  std_deg: number;
  phase: SummaryPhase;
  phase_value_deg: number;
  min_threshold: number | null;
  max_threshold: number | null;
  rating: SummaryRating;
}

export type StridePhase = "initial_contact" | "mid_stance" | "toe_off";
export type Side = "left" | "right";

/** Initial-contact detection strategy (mirrors backend CONTACT_METHODS). */
export type ContactMethod =
  | "forward_peak"
  | "forward_peak_delayed"
  | "foot_plant";

export const CONTACT_METHOD_OPTIONS: {
  value: ContactMethod;
  label: string;
  hint: string;
}[] = [
  {
    value: "foot_plant",
    label: "Foot plant",
    hint: "Frame where the foot is physically lowest — the true ground contact (default).",
  },
  {
    value: "forward_peak_delayed",
    label: "Delayed",
    hint: "Forward reach shifted ~30 ms later toward the plant.",
  },
  {
    value: "forward_peak",
    label: "Forward reach",
    hint: "Foot furthest ahead of the hip. Fires a few frames before the foot plants.",
  },
];

export interface StrideEvent {
  phase: StridePhase;
  side: Side;
  frame_number: number;
  timestamp_ms: number;
}

export interface StrideSummary {
  side: Side;
  num_contacts: number;
  num_strides: number;
  cadence_spm: number;
  cadence_rating: string | null;
}

export type Severity = "mild" | "moderate" | "severe";
export type Tier = "consistent" | "intermittent" | "isolated";
export type MetricUnit =
  | "ratio" | "degrees" | "percent" | "spm" | "centimeters" | string;

export interface FormProblem {
  problem_id: string;
  display_name: string;
  severity: Severity;
  confidence: number;
  side: Side | "both" | null;
  phase: string | null;
  description: string;
  recommendation: string;
  occurrences: number;
  total_strides: number;
  occurrence_pct: number;
  frames: number[];
  metric_value: number | null;
  threshold: number | null;
  metric_unit: MetricUnit | null;
  tier: Tier;
  outlier_strides_excluded: number;
  category: string | null;
  speed_band_adjusted: boolean;
  self_cal_applied: boolean;
}

export interface FormAnalysis {
  problems: FormProblem[];
  strike_pattern: string | null;
  asymmetry_index: Record<string, number>;
  speed_band: string | null;
  estimated_cadence: number | null;
  min_strides_met: boolean;
  low_confidence_warning: string | null;
}

export interface AnalysisResult {
  job_id: string;
  status: JobStatus;
  duration_sec: number;
  total_frames: number;
  analyzed_frames: number;
  video_fps: number;
  frame_angles: FrameEntry[];
  summary: AngleSummary[];
  stride_events: StrideEvent[];
  stride_summary: StrideSummary[];
  form_analysis: FormAnalysis;
  has_video: boolean;
}
