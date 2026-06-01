"use client";

import * as React from "react";
import { videoUrl } from "@/lib/api";
import { useAnalysis } from "@/store/useAnalysis";
import { formatClock } from "@/lib/format";

const RATES = [0.1, 0.25, 0.5, 1, 1.5, 2];
const ZOOM_MIN = 1;
const ZOOM_MAX = 4;
const ZOOM_STEP = 0.5;

/**
 * Custom media player for the annotated analysis video.
 *
 * The backend serves H.264/mp4 inline, so the <video> element decodes it
 * directly. Native controls are hidden in favour of a themed control bar so
 * the surface matches the dashboard; frame-accurate scrubbing lives in the
 * separate FrameControls. Zoom + drag-to-pan let the user inspect joint
 * detail. The store wiring (reportTime / seek channel) is preserved so
 * charts, timeline and the frame inspector stay in sync.
 */
export function VideoPlayer({
  jobId,
  videoRef,
}: {
  jobId: string;
  videoRef: React.RefObject<HTMLVideoElement>;
}) {
  const reportTime = useAnalysis((s) => s.reportTime);
  const seekNonce = useAnalysis((s) => s.seekNonce);
  const seekTargetMs = useAnalysis((s) => s.seekTargetMs);
  const stepFrame = useAnalysis((s) => s.stepFrame);

  const containerRef = React.useRef<HTMLDivElement>(null);
  const viewportRef = React.useRef<HTMLDivElement>(null);
  const [rate, setRate] = React.useState(1);
  const [playing, setPlaying] = React.useState(false);
  const [duration, setDuration] = React.useState(0);
  const [current, setCurrent] = React.useState(0);
  const [buffered, setBuffered] = React.useState(0);
  const [ready, setReady] = React.useState(false);
  const [failed, setFailed] = React.useState(false);
  const [fullscreen, setFullscreen] = React.useState(false);
  const [showUI, setShowUI] = React.useState(true);
  const hideTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  // Zoom + pan state.
  const [zoom, setZoom] = React.useState(1);
  const [pan, setPan] = React.useState({ x: 0, y: 0 });
  const drag = React.useRef<{ active: boolean; moved: boolean; startX: number; startY: number; baseX: number; baseY: number }>(
    { active: false, moved: false, startX: 0, startY: 0, baseX: 0, baseY: 0 }
  );

  // Clamp a pan offset so the scaled frame can't be dragged off the viewport.
  const clampPan = React.useCallback((x: number, y: number, z: number) => {
    const vp = viewportRef.current;
    if (!vp) return { x: 0, y: 0 };
    const maxX = (vp.clientWidth * (z - 1)) / 2;
    const maxY = (vp.clientHeight * (z - 1)) / 2;
    return {
      x: Math.max(-maxX, Math.min(maxX, x)),
      y: Math.max(-maxY, Math.min(maxY, y)),
    };
  }, []);

  const applyZoom = React.useCallback(
    (next: number) => {
      const z = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, Number(next.toFixed(2))));
      setZoom(z);
      setPan((p) => (z === 1 ? { x: 0, y: 0 } : clampPan(p.x, p.y, z)));
    },
    [clampPan]
  );

  // Respond to seek requests from charts / timeline / frame inspector.
  React.useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const target = seekTargetMs / 1000;
    if (Number.isFinite(target) && Math.abs(v.currentTime - target) > 0.005) {
      v.currentTime = target;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seekNonce]);

  React.useEffect(() => {
    const v = videoRef.current;
    if (v) v.playbackRate = rate;
  }, [rate, videoRef]);

  React.useEffect(() => {
    function onFsChange() {
      setFullscreen(document.fullscreenElement === containerRef.current);
    }
    document.addEventListener("fullscreenchange", onFsChange);
    return () => document.removeEventListener("fullscreenchange", onFsChange);
  }, []);

  function togglePlay() {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) void v.play();
    else v.pause();
  }

  function toggleFullscreen() {
    const el = containerRef.current;
    if (!el) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void el.requestFullscreen?.();
  }

  function onScrub(e: React.ChangeEvent<HTMLInputElement>) {
    const v = videoRef.current;
    if (!v || !duration) return;
    v.currentTime = (Number(e.target.value) / 1000) * duration;
  }

  function updateBuffered() {
    const v = videoRef.current;
    if (!v || !v.buffered.length || !v.duration) return;
    setBuffered(v.buffered.end(v.buffered.length - 1) / v.duration);
  }

  function nudgeUI() {
    setShowUI(true);
    if (hideTimer.current) clearTimeout(hideTimer.current);
    hideTimer.current = setTimeout(() => {
      if (videoRef.current && !videoRef.current.paused) setShowUI(false);
    }, 2500);
  }

  // ── Pan / play interaction on the video surface ──
  function onPointerDown(e: React.PointerEvent) {
    if (zoom === 1) return; // let click → play handle it
    drag.current = {
      active: true, moved: false,
      startX: e.clientX, startY: e.clientY,
      baseX: pan.x, baseY: pan.y,
    };
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
  }
  function onPointerMove(e: React.PointerEvent) {
    if (!drag.current.active) return;
    const dx = e.clientX - drag.current.startX;
    const dy = e.clientY - drag.current.startY;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) drag.current.moved = true;
    setPan(clampPan(drag.current.baseX + dx, drag.current.baseY + dy, zoom));
  }
  function onPointerUp(e: React.PointerEvent) {
    if (drag.current.active) {
      (e.target as HTMLElement).releasePointerCapture?.(e.pointerId);
      drag.current.active = false;
    }
  }
  function onVideoClick() {
    // A pan-drag shouldn't toggle playback.
    if (drag.current.moved) { drag.current.moved = false; return; }
    if (zoom === 1) togglePlay();
  }
  function onWheelZoom(e: React.WheelEvent) {
    if (!e.ctrlKey && !e.metaKey) return; // only zoom on ctrl/⌘+wheel
    e.preventDefault();
    applyZoom(zoom + (e.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP));
  }

  const progress = duration ? (current / duration) * 1000 : 0;
  const zoomed = zoom > 1;

  return (
    <div
      ref={containerRef}
      className="group relative overflow-hidden rounded-xl border border-border bg-black"
      onMouseMove={nudgeUI}
      onMouseLeave={() => playing && setShowUI(false)}
    >
      <div
        ref={viewportRef}
        className="relative mx-auto flex aspect-video max-h-[65vh] w-full items-center overflow-hidden bg-black"
        onWheel={onWheelZoom}
      >
        <video
          ref={videoRef}
          src={videoUrl(jobId)}
          playsInline
          preload="metadata"
          className={`h-full w-full bg-black object-contain ${zoomed ? (drag.current.active ? "cursor-grabbing" : "cursor-grab") : "cursor-pointer"}`}
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
            transformOrigin: "center center",
            transition: drag.current.active ? "none" : "transform 0.12s ease-out",
          }}
          onClick={onVideoClick}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPlay={() => { setPlaying(true); nudgeUI(); }}
          onPause={() => { setPlaying(false); setShowUI(true); }}
          onLoadedMetadata={(e) => {
            const v = e.currentTarget;
            v.playbackRate = rate;
            setDuration(v.duration || 0);
            setReady(true);
          }}
          onDurationChange={(e) => setDuration(e.currentTarget.duration || 0)}
          onTimeUpdate={(e) => {
            const v = e.currentTarget;
            setCurrent(v.currentTime);
            reportTime(v.currentTime * 1000);
          }}
          onProgress={updateBuffered}
          onWaiting={() => setReady(false)}
          onCanPlay={() => setReady(true)}
          onError={() => setFailed(true)}
        />

        {/* Loading spinner until first frame is decodable. */}
        {!ready && !failed && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/40">
            <div className="size-8 animate-spin rounded-full border-2 border-white/25 border-t-primary" />
          </div>
        )}

        {/* Center play affordance when paused (only at 1× so it doesn't block panning). */}
        {ready && !playing && !failed && !zoomed && (
          <button
            type="button"
            aria-label="Play"
            onClick={togglePlay}
            className="absolute inset-0 flex items-center justify-center bg-black/20 transition hover:bg-black/30"
          >
            <span className="flex size-16 items-center justify-center rounded-full bg-black/60 ring-1 ring-white/15 backdrop-blur">
              <PlayIcon className="ml-1 size-7 text-white" />
            </span>
          </button>
        )}

        {/* Zoom badge while zoomed. */}
        {zoomed && (
          <div className="pointer-events-none absolute left-3 top-3 rounded-md bg-black/60 px-2 py-1 text-xs font-medium text-white ring-1 ring-white/15">
            {zoom.toFixed(1)}× · drag to pan
          </div>
        )}

        {/* Codec / network failure fallback. */}
        {failed && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-surface p-6 text-center">
            <p className="text-sm font-medium">This clip can&apos;t play inline</p>
            <p className="max-w-xs text-xs text-muted-foreground">
              The annotated video couldn&apos;t be decoded by your browser. You can
              still download it and play it locally.
            </p>
            <a
              href={videoUrl(jobId)}
              download
              className="rounded-md border border-border bg-surface-2 px-3 py-1.5 text-sm font-medium hover:border-primary hover:text-primary"
            >
              Download annotated video
            </a>
          </div>
        )}

        {/* Control bar. */}
        {!failed && (
          <div
            className={`absolute inset-x-0 bottom-0 z-20 bg-gradient-to-t from-black/85 via-black/45 to-transparent px-3 pb-2.5 pt-8 transition-opacity duration-200 ${
              showUI || !playing ? "opacity-100" : "opacity-0"
            }`}
          >
            {/* Seek bar with buffered track. */}
            <div className="relative mb-2 h-1.5">
              <div className="absolute inset-0 rounded-full bg-white/20" />
              <div
                className="absolute inset-y-0 left-0 rounded-full bg-white/30"
                style={{ width: `${buffered * 100}%` }}
              />
              <div
                className="absolute inset-y-0 left-0 rounded-full bg-primary"
                style={{ width: `${progress / 10}%` }}
              />
              <input
                type="range"
                min={0}
                max={1000}
                value={Number.isFinite(progress) ? progress : 0}
                onChange={onScrub}
                aria-label="Seek"
                className="absolute inset-0 h-full w-full cursor-pointer appearance-none bg-transparent [&::-webkit-slider-thumb]:size-3 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-primary"
              />
            </div>

            <div className="flex items-center gap-1.5 text-white">
              <IconButton label={playing ? "Pause" : "Play"} onClick={togglePlay}>
                {playing ? <PauseIcon className="size-4" /> : <PlayIcon className="size-4" />}
              </IconButton>

              <IconButton label="Previous frame" onClick={() => stepFrame(-1)}>
                <StepIcon className="size-4 -scale-x-100" />
              </IconButton>
              <IconButton label="Next frame" onClick={() => stepFrame(1)}>
                <StepIcon className="size-4" />
              </IconButton>

              <span className="tabular ml-1 select-none text-xs text-white/80">
                {formatClock(current)} <span className="text-white/40">/</span>{" "}
                {formatClock(duration)}
              </span>

              <div className="ml-auto flex items-center gap-1.5">
                {/* Zoom controls */}
                <div className="flex items-center rounded-md border border-white/15 bg-black/40">
                  <IconButton label="Zoom out" onClick={() => applyZoom(zoom - ZOOM_STEP)}>
                    <MinusIcon className="size-4" />
                  </IconButton>
                  <button
                    type="button"
                    onClick={() => applyZoom(1)}
                    title="Reset zoom"
                    className="tabular w-10 select-none text-center text-xs text-white/90 hover:text-white"
                  >
                    {Math.round(zoom * 100)}%
                  </button>
                  <IconButton label="Zoom in" onClick={() => applyZoom(zoom + ZOOM_STEP)}>
                    <PlusIcon className="size-4" />
                  </IconButton>
                </div>

                <label className="sr-only" htmlFor="player-rate">Playback speed</label>
                <select
                  id="player-rate"
                  value={rate}
                  onChange={(e) => setRate(Number(e.target.value))}
                  className="tabular rounded border border-white/15 bg-black/50 px-1.5 py-1 text-xs text-white focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  {RATES.map((r) => (
                    <option key={r} value={r} className="bg-surface text-foreground">
                      {r}×
                    </option>
                  ))}
                </select>

                <IconButton
                  label={fullscreen ? "Exit fullscreen" : "Fullscreen"}
                  onClick={toggleFullscreen}
                >
                  <FullscreenIcon className="size-4" />
                </IconButton>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function IconButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="flex size-8 items-center justify-center rounded-md text-white/90 transition hover:bg-white/15 hover:text-white focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
    >
      {children}
    </button>
  );
}

/* Minimal inline glyphs — no decorative icon set. */
function PlayIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}
function PauseIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M6 5h4v14H6zM14 5h4v14h-4z" />
    </svg>
  );
}
function StepIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M6 5v14l9-7zM17 5h2v14h-2z" />
    </svg>
  );
}
function FullscreenIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M4 9V5a1 1 0 0 1 1-1h4M20 9V5a1 1 0 0 0-1-1h-4M4 15v4a1 1 0 0 0 1 1h4M20 15v4a1 1 0 0 1-1 1h-4" />
    </svg>
  );
}
function PlusIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}
function MinusIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
      <path d="M5 12h14" />
    </svg>
  );
}
