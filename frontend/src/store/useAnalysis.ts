import { create } from "zustand";
import {
  buildIndex,
  frameToMs,
  nearestFrame,
  stepAnalyzedFrame,
  type AnalysisIndex,
} from "@/lib/data";
import type { AnalysisResult } from "@/lib/types";

interface AnalysisState {
  result: AnalysisResult | null;
  index: AnalysisIndex | null;

  /** The single shared "current analyzed frame". */
  currentFrame: number;
  /** Live playback time in ms (may be between analyzed frames). */
  currentTimeMs: number;

  /** Seek request channel: the video player watches this. */
  seekNonce: number;
  seekTargetMs: number;

  setResult: (result: AnalysisResult) => void;

  /** Called by the video element on timeupdate (ms). Snaps currentFrame. */
  reportTime: (ms: number) => void;

  /** Move current frame to nearest analyzed frame and request a video seek. */
  seekToFrame: (frame: number) => void;
  seekToMs: (ms: number) => void;
  stepFrame: (dir: 1 | -1) => void;
}

export const useAnalysis = create<AnalysisState>()((set, get) => ({
  result: null,
  index: null,
  currentFrame: 0,
  currentTimeMs: 0,
  seekNonce: 0,
  seekTargetMs: 0,

  setResult: (result) => {
    const index = buildIndex(result);
    const first = index.frameNumbers[0] ?? 0;
    set({
      result,
      index,
      currentFrame: first,
      currentTimeMs: frameToMs(index, first),
    });
  },

  reportTime: (ms) => {
    const { index } = get();
    if (!index) {
      set({ currentTimeMs: ms });
      return;
    }
    const frame = nearestFrame(index, Math.round((ms / 1000) * index.fps));
    set({ currentTimeMs: ms, currentFrame: frame });
  },

  seekToFrame: (frame) => {
    const { index } = get();
    if (!index) return;
    const snapped = nearestFrame(index, frame);
    const ms = frameToMs(index, snapped);
    set((s) => ({
      currentFrame: snapped,
      currentTimeMs: ms,
      seekTargetMs: ms,
      seekNonce: s.seekNonce + 1,
    }));
  },

  seekToMs: (ms) => {
    const { index } = get();
    const frame = index
      ? nearestFrame(index, Math.round((ms / 1000) * index.fps))
      : get().currentFrame;
    set((s) => ({
      currentFrame: frame,
      currentTimeMs: ms,
      seekTargetMs: ms,
      seekNonce: s.seekNonce + 1,
    }));
  },

  stepFrame: (dir) => {
    const { index, currentFrame } = get();
    if (!index) return;
    const next = stepAnalyzedFrame(index, currentFrame, dir);
    get().seekToFrame(next);
  },
}));
