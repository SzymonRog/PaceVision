"use client";

import * as React from "react";
import type { AnalysisResult, Side, StridePhase } from "@/lib/types";
import { useAnalysis } from "@/store/useAnalysis";
import { Section } from "./section";
import { formatMs } from "@/lib/format";

const PHASE_COLOR: Record<StridePhase, string> = {
  initial_contact: "#A3E635",
  mid_stance: "#38BDF8",
  toe_off: "#FB923C",
};
const PHASE_LABEL: Record<StridePhase, string> = {
  initial_contact: "Initial contact",
  mid_stance: "Mid-stance",
  toe_off: "Toe-off",
};

export function StrideTimeline({ result }: { result: AnalysisResult }) {
  const currentTimeMs = useAnalysis((s) => s.currentTimeMs);
  const seekToFrame = useAnalysis((s) => s.seekToFrame);

  const total = result.total_frames || 1;
  const fps = result.video_fps || 30;
  const durationMs = (total / fps) * 1000;
  const playheadPct = durationMs > 0 ? Math.min(100, Math.max(0, (currentTimeMs / durationMs) * 100)) : 0;
  const sides: Side[] = ["left", "right"];

  return (
    <Section
      title="Stride & gait"
      description="Per-leg cadence and a timeline of every detected gait event. Click any marker to jump the video there."
    >
      {/* Per-side summary */}
      <div className="mb-5 grid gap-3 sm:grid-cols-2">
        {result.stride_summary.map((s) => (
          <div key={s.side} className="rounded-md border border-border bg-surface-2/40 p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="font-medium capitalize">{s.side} leg</span>
              {s.cadence_rating && (
                <span className="text-xs capitalize text-muted-foreground">{s.cadence_rating}</span>
              )}
            </div>
            <div className="grid grid-cols-3 gap-2 text-center">
              <Stat value={s.num_strides} label="strides" />
              <Stat value={s.num_contacts} label="contacts" />
              <Stat value={Math.round(s.cadence_spm)} label="spm" />
            </div>
          </div>
        ))}
      </div>

      {/* Legend */}
      <div className="mb-2 flex flex-wrap gap-3 text-xs text-muted-foreground">
        {(Object.keys(PHASE_COLOR) as StridePhase[]).map((p) => (
          <span key={p} className="inline-flex items-center gap-1.5">
            <span className="inline-block size-2.5 rounded-full" style={{ background: PHASE_COLOR[p] }} />
            {PHASE_LABEL[p]}
          </span>
        ))}
      </div>

      {/* Tracks */}
      <div className="flex flex-col gap-2">
        {sides.map((side) => {
          const events = result.stride_events.filter((e) => e.side === side);
          return (
            <div key={side} className="flex items-center gap-3">
              <span className="w-6 shrink-0 text-xs font-medium uppercase text-muted-foreground">
                {side[0]}
              </span>
              <div className="relative h-9 flex-1 rounded-md border border-border bg-surface-2/40">
                {/* current-time playhead */}
                <div
                  className="pointer-events-none absolute top-0 z-20 h-full w-0.5 bg-foreground/80"
                  style={{ left: `${playheadPct}%` }}
                />
                {events.map((ev) => {
                  const pct = (ev.frame_number / total) * 100;
                  return (
                    <div
                      key={`${ev.frame_number}-${ev.phase}`}
                      className="group absolute top-0 z-10 h-full"
                      style={{ left: `${pct}%` }}
                    >
                      <button
                        onClick={() => seekToFrame(ev.frame_number)}
                        aria-label={`${PHASE_LABEL[ev.phase]} at frame ${ev.frame_number}`}
                        className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 cursor-pointer rounded-full ring-2 ring-surface transition-transform hover:scale-150"
                        style={{ background: PHASE_COLOR[ev.phase] }}
                      />
                      {/* hover label */}
                      <span className="pointer-events-none absolute bottom-full left-1/2 z-30 mb-1 hidden -translate-x-1/2 whitespace-nowrap rounded-md border border-border bg-popover px-2 py-1 text-[11px] text-foreground shadow-lg group-hover:block">
                        {PHASE_LABEL[ev.phase]} · #{ev.frame_number} · {formatMs(ev.timestamp_ms)}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {result.form_analysis.estimated_cadence != null &&
        !result.form_analysis.min_strides_met && (
          <p className="mt-3 text-xs text-muted-foreground">
            Cadence is shown for reference only — this clip looks like slow-motion,
            so per-minute rates may not reflect real running cadence.
          </p>
        )}
    </Section>
  );
}

function Stat({ value, label }: { value: number; label: string }) {
  return (
    <div className="rounded bg-surface px-2 py-1.5">
      <div className="tabular text-lg font-semibold">{value}</div>
      <div className="text-[11px] text-muted-foreground">{label}</div>
    </div>
  );
}
