"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  ALLOWED_EXTENSIONS, MAX_SIZE_BYTES, uploadVideo, ApiError,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

function extOf(name: string) {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i).toLowerCase() : "";
}
function humanSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function UploadForm() {
  const router = useRouter();
  const inputRef = React.useRef<HTMLInputElement>(null);

  const [file, setFile] = React.useState<File | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [dragging, setDragging] = React.useState(false);
  const [showAdvanced, setShowAdvanced] = React.useState(false);
  const [skipFrames, setSkipFrames] = React.useState(1);
  const [detectionHeight, setDetectionHeight] = React.useState<number | "">("");
  const [uploading, setUploading] = React.useState(false);
  const [progress, setProgress] = React.useState(0);

  function validate(f: File): string | null {
    if (!ALLOWED_EXTENSIONS.includes(extOf(f.name))) {
      return `Unsupported file type. Allowed: ${ALLOWED_EXTENSIONS.join(", ")}.`;
    }
    if (f.size > MAX_SIZE_BYTES) {
      return `File is ${humanSize(f.size)} - the maximum is 500 MB.`;
    }
    return null;
  }

  function pickFile(f: File | undefined) {
    if (!f) return;
    const err = validate(f);
    if (err) {
      setError(err);
      setFile(null);
      return;
    }
    setError(null);
    setFile(f);
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    pickFile(e.dataTransfer.files?.[0]);
  }

  async function onSubmit() {
    if (!file) return;
    setUploading(true);
    setError(null);
    setProgress(0);
    try {
      const res = await uploadVideo(file, {
        skipFrames: skipFrames > 1 ? skipFrames : undefined,
        detectionHeight: detectionHeight ? Number(detectionHeight) : undefined,
        onProgress: setProgress,
      });
      router.push(`/processing/${res.job_id}`);
    } catch (e) {
      setUploading(false);
      setError(e instanceof ApiError ? e.message : "Upload failed. Please try again.");
    }
  }

  return (
    <div className="flex flex-col gap-5">
      {/* Dropzone */}
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload a video file"
        onClick={() => !uploading && inputRef.current?.click()}
        onKeyDown={(e) => {
          if ((e.key === "Enter" || e.key === " ") && !uploading) inputRef.current?.click();
        }}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cn(
          "group relative flex min-h-44 cursor-pointer flex-col items-center justify-center gap-2 rounded-md border border-dashed p-8 text-center transition-colors",
          dragging
            ? "border-primary bg-primary/5"
            : "border-border hover:border-primary/60 hover:bg-surface-2/40",
          uploading && "pointer-events-none opacity-70"
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ALLOWED_EXTENSIONS.join(",")}
          className="hidden"
          onChange={(e) => pickFile(e.target.files?.[0])}
        />
        {file ? (
          <div className="flex w-full items-center justify-between gap-3 rounded-md border border-border bg-surface-2 px-4 py-3 text-left">
            <div className="min-w-0">
              <div className="truncate text-sm font-medium">{file.name}</div>
              <div className="tabular text-xs text-muted-foreground">{humanSize(file.size)}</div>
            </div>
            {!uploading && (
              <button
                aria-label="Remove file"
                className="shrink-0 rounded px-2 py-1 text-xs text-muted-foreground hover:bg-background hover:text-foreground"
                onClick={(e) => { e.stopPropagation(); setFile(null); }}
              >
                Remove
              </button>
            )}
          </div>
        ) : (
          <>
            <p className="font-medium">Drop a clip here, or click to browse</p>
            <p className="text-sm text-muted-foreground">
              {ALLOWED_EXTENSIONS.join("  ")}
            </p>
          </>
        )}
      </div>

      {error && (
        <div
          role="alert"
          className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger"
        >
          {error}
        </div>
      )}

      {/* Advanced */}
      <div className="rounded-md border border-border">
        <button
          className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium"
          onClick={() => setShowAdvanced((s) => !s)}
          aria-expanded={showAdvanced}
        >
          <span>Advanced options</span>
          <span className="text-xs text-muted-foreground">{showAdvanced ? "Hide" : "Show"}</span>
        </button>
        {showAdvanced && (
          <div className="grid gap-5 border-t border-border p-4 animate-fade-in">
            <div>
              <div className="mb-1 flex items-center justify-between">
                <label className="text-sm font-medium">Frame skipping</label>
                <span className="tabular text-xs text-muted-foreground">
                  every {skipFrames} frame{skipFrames > 1 ? "s" : ""}
                </span>
              </div>
              <Slider value={skipFrames} min={1} max={10} onValueChange={setSkipFrames} />
              <p className="mt-1 text-xs text-muted-foreground">
                Higher is faster but analyzes fewer frames. Default 1 (analyze all).
              </p>
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">Detection height (px)</label>
              <input
                type="number"
                inputMode="numeric"
                min={240}
                max={1080}
                placeholder="auto (240-1080)"
                value={detectionHeight}
                onChange={(e) =>
                  setDetectionHeight(e.target.value === "" ? "" : Number(e.target.value))
                }
                className="tabular h-9 w-full rounded-md border border-border bg-surface-2 px-3 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                Optional. Downscale frames before pose detection to trade accuracy for speed.
              </p>
            </div>
          </div>
        )}
      </div>

      {uploading && (
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Uploading</span>
            <span className="tabular text-muted-foreground">{progress}%</span>
          </div>
          <Progress value={progress} />
        </div>
      )}

      <Button size="lg" disabled={!file || uploading} onClick={onSubmit}>
        {uploading ? "Uploading" : "Analyze form"}
      </Button>
    </div>
  );
}
