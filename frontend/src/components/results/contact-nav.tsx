"use client";

import * as React from "react";
import { SkipBack, SkipForward } from "lucide-react";
import { useAnalysis } from "@/store/useAnalysis";
import { filteredEvents, adjacentEvent } from "@/lib/data";
import type { Side, StridePhase } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { formatMs } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface ContactQuery {
  phase: StridePhase;
  side: Side | "both";
}

export function ContactNav({
  query,
  setQuery,
}: {
  query: ContactQuery;
  setQuery: (q: ContactQuery) => void;
}) {
  const index = useAnalysis((s) => s.index);
  const currentFrame = useAnalysis((s) => s.currentFrame);
  const seekToFrame = useAnalysis((s) => s.seekToFrame);

  const events = React.useMemo(
    () => (index ? filteredEvents(index, query) : []),
    [index, query]
  );

  // Active index in the filtered list (closest at/just before current).
  const activeIdx = React.useMemo(() => {
    let idx = -1;
    for (let i = 0; i < events.length; i++) {
      if (events[i].frame_number <= currentFrame) idx = i;
      else break;
    }
    return idx;
  }, [events, currentFrame]);

  if (!index) return null;

  const go = (dir: 1 | -1) => {
    const ev = adjacentEvent(events, currentFrame, dir);
    if (ev) seekToFrame(ev.frame_number);
  };

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Gait events
        </span>
        <span className="tabular text-xs text-muted-foreground">
          {activeIdx >= 0 ? activeIdx + 1 : "–"} / {events.length}
          {activeIdx >= 0 && ` (${events[activeIdx].side})`}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" size="icon-sm" aria-label="Previous event" onClick={() => go(-1)}>
          <SkipBack className="size-4" />
        </Button>
        <Button variant="secondary" size="icon-sm" aria-label="Next event" onClick={() => go(1)}>
          <SkipForward className="size-4" />
        </Button>

        <Select
          value={query.phase}
          onChange={(e) => setQuery({ ...query, phase: e.target.value as StridePhase })}
          aria-label="Event phase"
        >
          <option value="initial_contact">Initial contact</option>
          <option value="mid_stance">Mid-stance</option>
          <option value="toe_off">Toe-off</option>
        </Select>

        <Select
          value={query.side}
          onChange={(e) => setQuery({ ...query, side: e.target.value as Side | "both" })}
          aria-label="Side filter"
        >
          <option value="both">Both legs</option>
          <option value="left">Left</option>
          <option value="right">Right</option>
        </Select>
      </div>

      {/* Event picker list */}
      <div className="scroll-thin max-h-36 overflow-y-auto rounded-md border border-border">
        {events.length === 0 ? (
          <p className="p-3 text-xs text-muted-foreground">No events for this filter.</p>
        ) : (
          <ul className="divide-y divide-border">
            {events.map((ev, i) => (
              <li key={`${ev.frame_number}-${ev.side}`}>
                <button
                  onClick={() => seekToFrame(ev.frame_number)}
                  className={cn(
                    "flex w-full items-center justify-between px-3 py-1.5 text-left text-xs hover:bg-surface-2",
                    i === activeIdx && "bg-primary/10"
                  )}
                >
                  <span className="flex items-center gap-2">
                    <span
                      className={cn(
                        "inline-block size-2 rounded-full",
                        ev.side === "left" ? "bg-primary" : "bg-accent"
                      )}
                    />
                    <span className="capitalize">{ev.side}</span>
                  </span>
                  <span className="tabular text-muted-foreground">
                    #{ev.frame_number} · {formatMs(ev.timestamp_ms)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
