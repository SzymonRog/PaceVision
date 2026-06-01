"use client";

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { AlertTriangle, Loader2 } from "lucide-react";
import { subscribeStatus } from "@/lib/api";
import type { JobProgress } from "@/lib/types";
import { SiteHeader } from "@/components/site-header";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";

const STATUS_LABEL: Record<string, string> = {
  queued: "Queued",
  processing: "Analyzing pose & angles",
  completed: "Done",
  failed: "Failed",
};

export default function ProcessingPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [progress, setProgress] = React.useState<JobProgress | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!id) return;
    const stop = subscribeStatus(id, {
      onProgress: setProgress,
      onComplete: () => router.replace(`/results/${id}`),
      onError: (msg) => setError(msg),
    });
    return stop;
  }, [id, router]);

  const pct = progress?.progress_pct ?? 0;
  const status = progress?.status ?? "queued";

  return (
    <div className="min-h-dvh">
      <SiteHeader />
      <main className="container grid min-h-[70vh] place-items-center py-10">
        <Card className="w-full max-w-md">
          <CardContent className="flex flex-col items-center gap-6 pt-6 text-center">
            {error ? (
              <>
                <span className="grid size-12 place-items-center rounded-full bg-danger/10 text-danger">
                  <AlertTriangle className="size-6" />
                </span>
                <div>
                  <h1 className="font-display text-xl font-semibold">Analysis failed</h1>
                  <p className="mt-1 text-sm text-muted-foreground">{error}</p>
                </div>
                <Button onClick={() => router.push("/")}>Upload again</Button>
              </>
            ) : (
              <>
                <span className="grid size-12 place-items-center rounded-full bg-primary/10 text-primary">
                  <Loader2 className="size-6 animate-spin" />
                </span>
                <div>
                  <h1 className="font-display text-xl font-semibold">
                    {STATUS_LABEL[status] ?? "Processing"}
                  </h1>
                  <p className="mt-1 text-sm text-muted-foreground">
                    This can take a minute or two for long, high-frame-rate clips.
                  </p>
                </div>

                <div className="w-full">
                  <Progress value={pct} />
                  <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
                    <span className="tabular">{Math.round(pct)}%</span>
                    {progress && progress.total_frames > 0 && (
                      <span className="tabular">
                        {progress.frames_processed.toLocaleString()} /{" "}
                        {progress.total_frames.toLocaleString()} frames
                      </span>
                    )}
                  </div>
                </div>

                <Link
                  href="/"
                  className="text-xs text-muted-foreground underline-offset-4 hover:underline"
                >
                  Cancel and start over
                </Link>
              </>
            )}
          </CardContent>
        </Card>
      </main>
    </div>
  );
}
