import type { AngleName, MetricUnit, Severity, Tier } from "./types";

/** Human-readable label for an angle name. */
export function angleLabel(name: string): string {
  const side = name.startsWith("left_") ? "L" : name.startsWith("right_") ? "R" : "";
  const base = name.replace(/^left_|^right_/, "");
  const labels: Record<string, string> = {
    knee_flexion: "Knee flexion",
    hip_flexion: "Hip flexion",
    ankle_dorsiflexion: "Ankle dorsiflexion",
    arm_swing: "Arm swing",
    arm_drive: "Arm drive",
    trunk_lean: "Trunk lean",
  };
  const label = labels[base] ?? base.replace(/_/g, " ");
  return side ? `${label} (${side})` : label;
}

/** Base name without side prefix (e.g. left_knee_flexion -> knee_flexion). */
export function angleBase(name: string): string {
  return name.replace(/^left_|^right_/, "");
}

export function sideOf(name: string): "left" | "right" | null {
  if (name.startsWith("left_")) return "left";
  if (name.startsWith("right_")) return "right";
  return null;
}

/** mm:ss.mmm from milliseconds. */
export function formatMs(ms: number): string {
  if (!Number.isFinite(ms)) return "—";
  const totalSec = ms / 1000;
  const m = Math.floor(totalSec / 60);
  const s = Math.floor(totalSec % 60);
  const millis = Math.floor(ms % 1000);
  return `${m}:${s.toString().padStart(2, "0")}.${millis.toString().padStart(3, "0")}`;
}

/** mm:ss from seconds (player time). */
export function formatClock(sec: number): string {
  if (!Number.isFinite(sec)) return "0:00";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function formatDeg(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v.toFixed(digits)}°`;
}

/** Render a problem metric value with its unit. */
export function formatMetric(value: number | null, unit: MetricUnit | null): string {
  if (value == null) return "—";
  switch (unit) {
    case "degrees":
      return `${value.toFixed(1)}°`;
    case "percent":
      return `${value.toFixed(1)}%`;
    case "spm":
      return `${value.toFixed(0)} spm`;
    case "centimeters":
      return `${value.toFixed(1)} cm`;
    case "ratio":
      return value.toFixed(3);
    default:
      return value.toFixed(2);
  }
}

export const severityRank: Record<Severity, number> = {
  severe: 3,
  moderate: 2,
  mild: 1,
};

export const tierRank: Record<Tier, number> = {
  consistent: 3,
  intermittent: 2,
  isolated: 1,
};

export const ALL_ANGLES: AngleName[] = [
  "left_knee_flexion", "right_knee_flexion",
  "left_hip_flexion", "right_hip_flexion",
  "left_ankle_dorsiflexion", "right_ankle_dorsiflexion",
  "left_arm_swing", "right_arm_swing",
  "left_arm_drive", "right_arm_drive",
  "trunk_lean",
];

/** Distinct, accessible-ish colors for chart series (lime-led categorical). */
export const SERIES_COLORS: Record<string, string> = {
  knee_flexion: "#A3E635",
  hip_flexion: "#FB923C",
  ankle_dorsiflexion: "#38BDF8",
  arm_swing: "#F59E0B",
  arm_drive: "#F472B6",
  trunk_lean: "#E6EDF3",
};
