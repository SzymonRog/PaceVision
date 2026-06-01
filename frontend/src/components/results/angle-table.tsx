"use client";

import type { AnalysisResult, SummaryRating } from "@/lib/types";
import { angleLabel, formatDeg } from "@/lib/format";
import { Section } from "./section";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

function RatingBadge({ rating }: { rating: SummaryRating }) {
  if (rating === "in_range")
    return <Badge variant="success">In range</Badge>;
  if (rating === "out_of_range")
    return <Badge variant="danger">Out of range</Badge>;
  return <Badge variant="neutral">No reference</Badge>;
}

function phaseLabel(phase: string) {
  return phase.replace(/_/g, " ");
}

export function AngleTable({ result }: { result: AnalysisResult }) {
  const rows = result.summary;

  return (
    <Section
      title="All angles"
      description="Phase-aware summary for every measured joint angle."
    >
      <div className="scroll-thin -mx-1 overflow-x-auto px-1">
        <table className="w-full min-w-[640px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
              <th className="py-2 pr-3 font-medium">Angle</th>
              <th className="py-2 pr-3 font-medium">Phase</th>
              <th className="py-2 pr-3 text-right font-medium">Value</th>
              <th className="py-2 pr-3 text-right font-medium">Optimal</th>
              <th className="py-2 pr-3 font-medium">Rating</th>
              <th className="py-2 pr-3 text-right font-medium">Mean</th>
              <th className="py-2 pr-3 text-right font-medium">Min</th>
              <th className="py-2 pr-3 text-right font-medium">Max</th>
              <th className="py-2 text-right font-medium">SD</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const noRef = r.rating === "no_reference";
              const range =
                r.min_threshold != null && r.max_threshold != null
                  ? `${r.min_threshold.toFixed(0)}–${r.max_threshold.toFixed(0)}°`
                  : "—";
              return (
                <tr
                  key={r.name}
                  className={cn(
                    "border-b border-border/60 last:border-0",
                    noRef && "text-muted-foreground"
                  )}
                >
                  <td className="py-2 pr-3 font-medium text-foreground">{angleLabel(r.name)}</td>
                  <td className="py-2 pr-3 capitalize">{phaseLabel(r.phase)}</td>
                  <td className="tabular py-2 pr-3 text-right">{formatDeg(r.phase_value_deg)}</td>
                  <td className="tabular py-2 pr-3 text-right">{range}</td>
                  <td className="py-2 pr-3"><RatingBadge rating={r.rating} /></td>
                  <td className="tabular py-2 pr-3 text-right">{formatDeg(r.mean_deg)}</td>
                  <td className="tabular py-2 pr-3 text-right">{formatDeg(r.min_deg)}</td>
                  <td className="tabular py-2 pr-3 text-right">{formatDeg(r.max_deg)}</td>
                  <td className="tabular py-2 text-right">{r.std_deg.toFixed(1)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-muted-foreground">
        “No reference” rows (ankle &amp; arms) are shown as data only — there’s no
        clinical pass/fail range for them in side view.
      </p>
    </Section>
  );
}
