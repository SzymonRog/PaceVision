"use client";

import { Info } from "lucide-react";
import type { AnalysisResult } from "@/lib/types";
import { Badge } from "@/components/ui/badge";

export function ScoreSummary({ result }: { result: AnalysisResult }) {
  const fa = result.form_analysis;

  return (
    <section className="rounded-lg border border-border bg-surface p-5">
      <div className="flex flex-wrap items-center gap-2">
        {fa.strike_pattern && (
          <Badge variant="neutral">{fa.strike_pattern.replace(/_/g, " ")}</Badge>
        )}
        {fa.speed_band && (
          <Badge variant="neutral">{fa.speed_band} pace</Badge>
        )}
        {fa.estimated_cadence != null && (
          <Badge variant="neutral">
            <span className="tabular">{Math.round(fa.estimated_cadence)}</span> spm
          </Badge>
        )}
        <Badge variant="neutral">
          <span className="tabular">{result.analyzed_frames.toLocaleString()}</span>{" "}
          frames · <span className="tabular">{result.video_fps}</span> fps
        </Badge>
      </div>

      {!fa.min_strides_met && fa.low_confidence_warning && (
        <div
          role="status"
          className="mt-4 flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-warning"
        >
          <Info className="mt-0.5 size-4 shrink-0" />
          <span>{fa.low_confidence_warning}</span>
        </div>
      )}
    </section>
  );
}
