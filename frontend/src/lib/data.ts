import { ALL_ANGLES } from "./format";
import type {
  AnalysisResult,
  FrameEntry,
  StrideEvent,
  StridePhase,
  Side,
} from "./types";

export interface AnglePoint {
  frame: number;
  ms: number;
  value: number;
}

export interface AnalysisIndex {
  /** sorted list of analyzed frame numbers */
  frameNumbers: number[];
  /** frame_number -> entry */
  byFrame: Map<number, FrameEntry>;
  /** angle name -> time series (only analyzed frames where present) */
  series: Record<string, AnglePoint[]>;
  /** stride events grouped & sorted by phase then side */
  eventsByPhase: Record<StridePhase, StrideEvent[]>;
  fps: number;
  totalFrames: number;
}

/** Parse the result once into fast lookup structures. */
export function buildIndex(result: AnalysisResult): AnalysisIndex {
  const byFrame = new Map<number, FrameEntry>();
  const frameNumbers: number[] = [];
  for (const f of result.frame_angles) {
    byFrame.set(f.frame_number, f);
    frameNumbers.push(f.frame_number);
  }
  frameNumbers.sort((a, b) => a - b);

  const series: Record<string, AnglePoint[]> = {};
  for (const name of ALL_ANGLES) series[name] = [];
  for (const fn of frameNumbers) {
    const entry = byFrame.get(fn)!;
    for (const name of ALL_ANGLES) {
      const a = entry.angles[name];
      if (a && Number.isFinite(a.value_deg)) {
        series[name].push({ frame: fn, ms: entry.timestamp_ms, value: a.value_deg });
      }
    }
  }

  const eventsByPhase: Record<StridePhase, StrideEvent[]> = {
    initial_contact: [],
    mid_stance: [],
    toe_off: [],
  };
  for (const ev of result.stride_events) {
    if (eventsByPhase[ev.phase]) eventsByPhase[ev.phase].push(ev);
  }
  for (const phase of Object.keys(eventsByPhase) as StridePhase[]) {
    eventsByPhase[phase].sort((a, b) => a.frame_number - b.frame_number);
  }

  return {
    frameNumbers,
    byFrame,
    series,
    eventsByPhase,
    fps: result.video_fps,
    totalFrames: result.total_frames,
  };
}

/** Nearest analyzed frame number to a target (binary search). */
export function nearestFrame(index: AnalysisIndex, target: number): number {
  const arr = index.frameNumbers;
  if (arr.length === 0) return target;
  let lo = 0;
  let hi = arr.length - 1;
  if (target <= arr[0]) return arr[0];
  if (target >= arr[hi]) return arr[hi];
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (arr[mid] === target) return arr[mid];
    if (arr[mid] < target) lo = mid + 1;
    else hi = mid - 1;
  }
  // lo is the first element > target, hi is last < target
  const after = arr[lo];
  const before = arr[hi];
  return target - before <= after - target ? before : after;
}

/** Index into frameNumbers for stepping; returns position of nearest. */
function nearestPos(index: AnalysisIndex, target: number): number {
  const nf = nearestFrame(index, target);
  // frameNumbers is sorted; find position
  let lo = 0;
  let hi = index.frameNumbers.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (index.frameNumbers[mid] === nf) return mid;
    if (index.frameNumbers[mid] < nf) lo = mid + 1;
    else hi = mid - 1;
  }
  return 0;
}

/** Step to next/previous analyzed frame. */
export function stepAnalyzedFrame(
  index: AnalysisIndex,
  current: number,
  dir: 1 | -1
): number {
  const pos = nearestPos(index, current);
  const next = Math.min(index.frameNumbers.length - 1, Math.max(0, pos + dir));
  return index.frameNumbers[next];
}

/** ms for a given frame number (from analyzed entry, else derived from fps). */
export function frameToMs(index: AnalysisIndex, frame: number): number {
  const e = index.byFrame.get(frame);
  if (e) return e.timestamp_ms;
  return (frame / index.fps) * 1000;
}

export function msToFrame(index: AnalysisIndex, ms: number): number {
  return Math.round((ms / 1000) * index.fps);
}

export interface ContactQuery {
  phase: StridePhase;
  side: Side | "both";
}

export function filteredEvents(index: AnalysisIndex, q: ContactQuery): StrideEvent[] {
  const list = index.eventsByPhase[q.phase] ?? [];
  return q.side === "both" ? list : list.filter((e) => e.side === q.side);
}

/** Find prev/next event around a frame within a filtered list. */
export function adjacentEvent(
  events: StrideEvent[],
  currentFrame: number,
  dir: 1 | -1
): StrideEvent | null {
  if (events.length === 0) return null;
  if (dir === 1) {
    for (const e of events) if (e.frame_number > currentFrame) return e;
    return null;
  }
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].frame_number < currentFrame) return events[i];
  }
  return null;
}

/**
 * Downsample a series to ~maxPoints using largest-triangle-three-buckets-ish
 * stride sampling (keeps peaks reasonably). Cheap and good enough for charts.
 */
export function downsample(points: AnglePoint[], maxPoints = 800): AnglePoint[] {
  if (points.length <= maxPoints) return points;
  const step = points.length / maxPoints;
  const out: AnglePoint[] = [];
  for (let i = 0; i < maxPoints; i++) {
    const start = Math.floor(i * step);
    const end = Math.min(points.length, Math.floor((i + 1) * step));
    // pick the extremum in the bucket to preserve peaks
    let pick = points[start];
    let maxDev = -1;
    const mid = points[Math.floor((start + end) / 2)]?.value ?? pick.value;
    for (let j = start; j < end; j++) {
      const dev = Math.abs(points[j].value - mid);
      if (dev > maxDev) {
        maxDev = dev;
        pick = points[j];
      }
    }
    out.push(pick);
  }
  return out;
}
