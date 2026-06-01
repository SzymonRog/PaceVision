"use client";

import { FileDown, Film } from "lucide-react";
import type { AnalysisResult } from "@/lib/types";
import { notebookUrl, videoUrl } from "@/lib/api";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function Downloads({ result }: { result: AnalysisResult }) {
  const completed = result.status === "completed";
  const cls = cn(buttonVariants({ variant: "outline", size: "sm" }));
  return (
    <div className="flex items-center gap-2">
      {completed && result.has_video && (
        <a href={videoUrl(result.job_id)} download className={cls} title="Download annotated MP4">
          <Film className="size-4" />
          <span className="hidden sm:inline">Video</span>
        </a>
      )}
      {completed && (
        <a href={notebookUrl(result.job_id)} download className={cls} title="Download Jupyter notebook">
          <FileDown className="size-4" />
          <span className="hidden sm:inline">Notebook</span>
        </a>
      )}
    </div>
  );
}
