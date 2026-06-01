"use client";

import { useAnalysis } from "@/store/useAnalysis";
import { ALL_ANGLES, angleLabel, formatDeg } from "@/lib/format";

export function PerFrameReadout() {
  const index = useAnalysis((s) => s.index);
  const currentFrame = useAnalysis((s) => s.currentFrame);
  if (!index) return null;

  const entry = index.byFrame.get(currentFrame);

  return (
    <div className="rounded-lg border border-border bg-surface p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Angles this frame
        </span>
        {!entry && (
          <span className="text-xs text-warning">no data (skipped frame)</span>
        )}
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5">
        {ALL_ANGLES.map((name) => {
          const a = entry?.angles[name];
          return (
            <div key={name} className="flex items-center justify-between gap-2">
              <dt className="truncate text-xs text-muted-foreground">{angleLabel(name)}</dt>
              <dd className="tabular text-xs font-medium">
                {a ? formatDeg(a.value_deg) : "—"}
              </dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}
