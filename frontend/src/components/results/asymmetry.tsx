"use client";

import type { AnalysisResult } from "@/lib/types";
import { angleLabel } from "@/lib/format";
import { Section } from "./section";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const NOTABLE = 10; // % — informational threshold

export function Asymmetry({ result }: { result: AnalysisResult }) {
  const entries = Object.entries(result.form_analysis.asymmetry_index ?? {});
  if (entries.length === 0) return null;

  const max = Math.max(NOTABLE, ...entries.map(([, v]) => v));

  return (
    <Section
      title="Left / right symmetry"
      description="Difference between sides per angle (informational)."
    >
      <div className="flex flex-col gap-2.5">
        {entries
          .sort((a, b) => b[1] - a[1])
          .map(([name, value]) => {
            const notable = value >= NOTABLE;
            return (
              <div key={name} className="flex items-center gap-3">
                <span className="w-40 shrink-0 truncate text-sm">{angleLabel(name)}</span>
                <div className="relative h-2 flex-1 overflow-hidden rounded-full bg-surface-2">
                  <div
                    className={cn("h-full rounded-full", notable ? "bg-warning" : "bg-primary")}
                    style={{ width: `${Math.min(100, (value / max) * 100)}%` }}
                  />
                </div>
                <span className="tabular w-12 shrink-0 text-right text-sm">{value.toFixed(1)}%</span>
                {notable ? (
                  <Badge variant="warning">notable</Badge>
                ) : (
                  <Badge variant="neutral">balanced</Badge>
                )}
              </div>
            );
          })}
      </div>
      <p className="mt-3 text-xs text-muted-foreground">
        The backend no longer flags angle asymmetry as a problem — values above{" "}
        {NOTABLE}% are highlighted here purely for your awareness.
      </p>
    </Section>
  );
}
