"use client";

import * as React from "react";
import type { AnalysisResult } from "@/lib/types";
import { useAnalysis } from "@/store/useAnalysis";
import { filteredEvents, adjacentEvent } from "@/lib/data";
import { VideoPlayer } from "./video-player";
import type { ContactQuery } from "./contact-nav";

/**
 * Full-width annotated player at the top of the results page. Seeking from any
 * component (timeline marker, gait event, chart, problem) is reflected here.
 * `query` is owned by the parent so the keyboard contact-jump and the
 * ContactNav stay in sync.
 */
export function VideoPanel({
  result,
  query,
}: {
  result: AnalysisResult;
  query: ContactQuery;
}) {
  const videoRef = React.useRef<HTMLVideoElement>(null);

  // Keyboard shortcuts: ←/→ step frame, space play/pause, [ ] jump contact.
  React.useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      const store = useAnalysis.getState();

      switch (e.key) {
        case "ArrowLeft":
          e.preventDefault();
          store.stepFrame(-1);
          break;
        case "ArrowRight":
          e.preventDefault();
          store.stepFrame(1);
          break;
        case " ":
          e.preventDefault();
          if (videoRef.current) {
            if (videoRef.current.paused) void videoRef.current.play();
            else videoRef.current.pause();
          }
          break;
        case "[":
        case "]": {
          const idx = store.index;
          if (!idx) break;
          e.preventDefault();
          const events = filteredEvents(idx, query);
          const ev = adjacentEvent(events, store.currentFrame, e.key === "]" ? 1 : -1);
          if (ev) store.seekToFrame(ev.frame_number);
          break;
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [query]);

  return (
    <div className="mt-6">
      <VideoPlayer jobId={result.job_id} videoRef={videoRef} />
    </div>
  );
}
