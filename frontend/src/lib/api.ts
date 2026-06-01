import type { AnalysisResult, ContactMethod, JobCreated, JobProgress } from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://127.0.0.1:8000";

export const ALLOWED_EXTENSIONS = [".mp4", ".mov", ".avi", ".mkv", ".webm"];
export const MAX_SIZE_BYTES = 500 * 1024 * 1024; // 500 MB

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

/** Friendly message for the resilience-relevant status codes. */
export function messageForStatus(status: number, fallback?: string): string {
  switch (status) {
    case 404:
      return "This analysis could not be found — the job may have expired. Please upload your video again.";
    case 409:
      return "The analysis isn't ready yet. Hang tight while it finishes processing.";
    case 413:
      return "That file is too large. The maximum upload size is 500 MB.";
    case 422:
      return "Analysis failed for this video. Try a clear side-view clip and upload again.";
    default:
      return fallback || "Something went wrong. Please try again.";
  }
}

export interface UploadOptions {
  skipFrames?: number; // 1–10
  detectionHeight?: number; // 240–1080
  signal?: AbortSignal;
  onProgress?: (pct: number) => void;
}

/** Upload a video via multipart. Uses XHR so we can surface upload progress. */
export function uploadVideo(file: File, opts: UploadOptions = {}): Promise<JobCreated> {
  const params = new URLSearchParams();
  if (opts.skipFrames) params.set("skip_frames", String(opts.skipFrames));
  if (opts.detectionHeight) params.set("detection_height", String(opts.detectionHeight));
  const qs = params.toString();
  const url = `${API_BASE}/api/analyze-video${qs ? `?${qs}` : ""}`;

  return new Promise<JobCreated>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.responseType = "json";

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && opts.onProgress) {
        opts.onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.response as JobCreated);
      } else {
        const msg = (xhr.response && (xhr.response.detail || xhr.response.error)) as
          | string
          | undefined;
        reject(new ApiError(xhr.status, messageForStatus(xhr.status, msg)));
      }
    };
    xhr.onerror = () =>
      reject(new ApiError(0, "Network error during upload. Check your connection."));
    if (opts.signal) {
      opts.signal.addEventListener("abort", () => xhr.abort());
    }

    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

export async function fetchResult(
  jobId: string,
  contactMethod?: ContactMethod
): Promise<AnalysisResult> {
  const qs = contactMethod ? `?contact_method=${contactMethod}` : "";
  const res = await fetch(`${API_BASE}/api/analyze-video/${jobId}/result${qs}`);
  if (!res.ok) throw new ApiError(res.status, messageForStatus(res.status));
  return (await res.json()) as AnalysisResult;
}

export function videoUrl(jobId: string): string {
  return `${API_BASE}/api/analyze-video/${jobId}/video`;
}
export function notebookUrl(jobId: string): string {
  return `${API_BASE}/api/analyze-video/${jobId}/notebook`;
}

/**
 * Subscribe to the SSE status stream. Falls back to polling /result if the
 * stream errors. Returns an unsubscribe function.
 */
export function subscribeStatus(
  jobId: string,
  handlers: {
    onProgress: (p: JobProgress) => void;
    onComplete: () => void;
    onError: (message: string) => void;
  }
): () => void {
  let closed = false;
  let es: EventSource | null = null;
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  const startPolling = () => {
    if (pollTimer || closed) return;
    pollTimer = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/analyze-video/${jobId}/result`);
        if (res.status === 200) {
          stop();
          handlers.onComplete();
        } else if (res.status === 409) {
          // still processing — keep polling
        } else {
          stop();
          handlers.onError(messageForStatus(res.status));
        }
      } catch {
        /* transient — keep polling */
      }
    }, 2000);
  };

  const stop = () => {
    closed = true;
    es?.close();
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  };

  try {
    es = new EventSource(`${API_BASE}/api/analyze-video/${jobId}/status`);
    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as JobProgress;
        handlers.onProgress(data);
        if (data.status === "completed") {
          stop();
          handlers.onComplete();
        } else if (data.status === "failed") {
          stop();
          handlers.onError(data.error || messageForStatus(422));
        }
      } catch {
        /* ignore malformed keep-alive frames */
      }
    };
    es.onerror = () => {
      // SSE dropped — close and fall back to polling.
      es?.close();
      if (!closed) startPolling();
    };
  } catch {
    startPolling();
  }

  return stop;
}
