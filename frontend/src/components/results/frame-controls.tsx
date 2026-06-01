"use client";

import * as React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useAnalysis } from "@/store/useAnalysis";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { formatMs } from "@/lib/format";
import { cn } from "@/lib/utils";

export function FrameControls() {
  const index = useAnalysis((s) => s.index);
  const currentFrame = useAnalysis((s) => s.currentFrame);
  const stepFrame = useAnalysis((s) => s.stepFrame);
  const seekToFrame = useAnalysis((s) => s.seekToFrame);

  const [input, setInput] = React.useState(String(currentFrame));
  React.useEffect(() => setInput(String(currentFrame)), [currentFrame]);

  if (!index) return null;
  const total = index.totalFrames;
  const ms = index.byFrame.get(currentFrame)?.timestamp_ms ?? (currentFrame / index.fps) * 1000;
  const isAnalyzed = index.byFrame.has(currentFrame);

  return (
    <div className="flex h-full flex-col gap-3 rounded-lg border border-border bg-surface p-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Frame inspector
        </span>
        <span
          className={cn(
            "rounded-full px-2 py-0.5 text-[11px] font-medium",
            isAnalyzed ? "bg-success/10 text-success" : "bg-warning/10 text-warning"
          )}
        >
          {isAnalyzed ? "analyzed" : "interpolated"}
        </span>
      </div>

      {/* Prominent readout fills the available height. */}
      <div className="flex flex-1 flex-col items-center justify-center gap-1 py-1">
        <div className="flex items-end gap-1">
          <span className="tabular font-display text-4xl font-semibold leading-none">
            {currentFrame}
          </span>
          <span className="tabular mb-0.5 text-sm text-muted-foreground">/ {total - 1}</span>
        </div>
        <span className="tabular text-xs text-muted-foreground">{formatMs(ms)}</span>
      </div>

      <div className="flex items-center justify-center gap-2">
        <Button
          variant="secondary"
          size="icon-sm"
          aria-label="Previous analyzed frame"
          onClick={() => stepFrame(-1)}
        >
          <ChevronLeft className="size-4" />
        </Button>

        <input
          aria-label="Frame number"
          value={input}
          inputMode="numeric"
          onChange={(e) => setInput(e.target.value.replace(/[^0-9]/g, ""))}
          onBlur={() => {
            const n = Math.max(0, Math.min(total - 1, Number(input) || 0));
            seekToFrame(n);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          }}
          className="tabular h-8 w-24 rounded-md border border-border bg-surface-2 px-2 text-center text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        />

        <Button
          variant="secondary"
          size="icon-sm"
          aria-label="Next analyzed frame"
          onClick={() => stepFrame(1)}
        >
          <ChevronRight className="size-4" />
        </Button>
      </div>

      <Slider
        value={currentFrame}
        min={0}
        max={Math.max(0, total - 1)}
        onValueChange={(v) => seekToFrame(v)}
        aria-label="Scrub to frame"
      />

      <p className="text-center text-[11px] text-muted-foreground">
        ←/→ step frame · space play/pause · [ ] jump contact
      </p>
    </div>
  );
}
