"use client";

import * as React from "react";
import { ChevronDown } from "lucide-react";
import type { FormProblem, Severity } from "@/lib/types";
import { useAnalysis } from "@/store/useAnalysis";
import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";
import { formatMetric } from "@/lib/format";
import { cn } from "@/lib/utils";

const SEVERITY: Record<
  Severity,
  { label: string; variant: "danger" | "warning" | "neutral"; bar: string }
> = {
  severe: { label: "Severe", variant: "danger", bar: "bg-danger" },
  moderate: { label: "Moderate", variant: "warning", bar: "bg-warning" },
  mild: { label: "Mild", variant: "neutral", bar: "bg-muted-foreground/40" },
};

export function ProblemCard({
  problem,
  defaultOpen = false,
}: {
  problem: FormProblem;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = React.useState(defaultOpen);
  const seekToFrame = useAnalysis((s) => s.seekToFrame);
  const sev = SEVERITY[problem.severity];

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-md border bg-surface-2/40",
        problem.tier === "isolated" ? "border-dashed border-border opacity-90" : "border-border"
      )}
    >
      {/* Severity shown as a colored left accent (no icon). */}
      <span aria-hidden className={cn("absolute inset-y-0 left-0 w-1", sev.bar)} />
      <button
        className="flex w-full items-start gap-3 p-3 pl-4 text-left"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{problem.display_name}</span>
            <Badge variant={sev.variant}>{sev.label}</Badge>
            <Badge variant="outline" className="capitalize">{problem.tier}</Badge>
            {problem.side && problem.side !== "both" && (
              <Badge variant="neutral" className="uppercase">{problem.side}</Badge>
            )}
          </div>
          <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
            {problem.description}
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span className="tabular">
              {problem.occurrences}/{problem.total_strides} strides
              {" "}({problem.occurrence_pct.toFixed(0)}%)
            </span>
            {problem.metric_value != null && (
              <span className="tabular">
                {formatMetric(problem.metric_value, problem.metric_unit)}
                {problem.threshold != null && (
                  <span className="text-muted-foreground/70">
                    {" "}vs {formatMetric(problem.threshold, problem.metric_unit)}
                  </span>
                )}
              </span>
            )}
          </div>
        </div>
        <ChevronDown
          className={cn("mt-1 size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")}
        />
      </button>

      {open && (
        <div className="space-y-3 border-t border-border p-3 animate-fade-in">
          <div className="rounded-md border-l-2 border-primary bg-primary/10 p-3 text-sm">
            <div className="mb-1 text-xs font-medium uppercase tracking-wide text-primary">
              Recommendation
            </div>
            {problem.recommendation}
          </div>

          {/* Metadata badges */}
          <div className="flex flex-wrap gap-2">
            {problem.speed_band_adjusted && (
              <Tooltip content="Thresholds were adjusted for your estimated running speed band.">
                <Badge variant="neutral">speed-adjusted</Badge>
              </Tooltip>
            )}
            {problem.self_cal_applied && (
              <Tooltip content="Flagged relative to your own stride distribution (self-calibration), reducing false positives.">
                <Badge variant="neutral">self-calibrated</Badge>
              </Tooltip>
            )}
            {problem.outlier_strides_excluded > 0 && (
              <Tooltip content="Statistical outlier strides were excluded before evaluating this metric.">
                <Badge variant="neutral">
                  {problem.outlier_strides_excluded} outliers excluded
                </Badge>
              </Tooltip>
            )}
            {problem.category && <Badge variant="outline">{problem.category}</Badge>}
          </div>

          {/* Affected frames */}
          {problem.frames.length > 0 && (
            <div>
              <div className="mb-1.5 text-xs font-medium text-muted-foreground">
                Jump to an affected frame:
              </div>
              <div className="flex flex-wrap gap-1.5">
                {problem.frames.slice(0, 24).map((f) => (
                  <button
                    key={f}
                    onClick={() => seekToFrame(f)}
                    className="tabular rounded border border-border bg-surface px-2 py-0.5 text-xs hover:border-primary hover:text-primary"
                  >
                    #{f}
                  </button>
                ))}
                {problem.frames.length > 24 && (
                  <span className="self-center text-xs text-muted-foreground">
                    +{problem.frames.length - 24} more
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
