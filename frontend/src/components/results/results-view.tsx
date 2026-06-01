"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Loader2 } from "lucide-react";
import { fetchResult, ApiError } from "@/lib/api";
import { useAnalysis } from "@/store/useAnalysis";
import type { AnalysisResult, ContactMethod } from "@/lib/types";
import { SiteHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import { ScoreSummary } from "./score-summary";
import { Downloads } from "./downloads";
import { VideoPanel } from "./video-panel";
import { TopProblems } from "./top-problems";
import { AngleCharts } from "./angle-charts";
import { FormProblems } from "./form-problems";
import { AngleTable } from "./angle-table";
import { StrideTimeline } from "./stride-timeline";
import { Asymmetry } from "./asymmetry";
import { ContactNav, type ContactQuery } from "./contact-nav";
import { ContactMethodSelect } from "./contact-method-select";
import { PerFrameReadout } from "./per-frame-readout";
import { FrameControls } from "./frame-controls";

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; result: AnalysisResult };

export function ResultsView({ jobId }: { jobId: string }) {
  const router = useRouter();
  const setResult = useAnalysis((s) => s.setResult);
  const [state, setState] = React.useState<State>({ kind: "loading" });
  const [query, setQuery] = React.useState<ContactQuery>({
    phase: "initial_contact",
    side: "both",
  });
  const [contactMethod, setContactMethod] =
    React.useState<ContactMethod>("foot_plant");
  const [methodLoading, setMethodLoading] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const result = await fetchResult(jobId);
        if (cancelled) return;
        setResult(result);
        setState({ kind: "ready", result });
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 409) {
          router.replace(`/processing/${jobId}`);
          return;
        }
        setState({
          kind: "error",
          message: e instanceof ApiError ? e.message : "Could not load this analysis.",
        });
      }
    })();
    return () => { cancelled = true; };
  }, [jobId, router, setResult]);

  const onMethodChange = React.useCallback(
    (method: ContactMethod) => {
      setContactMethod(method);
      setMethodLoading(true);
      (async () => {
        try {
          const result = await fetchResult(jobId, method);
          setResult(result);
          setState({ kind: "ready", result });
        } catch (e) {
          setState({
            kind: "error",
            message:
              e instanceof ApiError ? e.message : "Could not recompute this analysis.",
          });
        } finally {
          setMethodLoading(false);
        }
      })();
    },
    [jobId, setResult]
  );

  if (state.kind === "loading") {
    return (
      <div className="min-h-dvh">
        <SiteHeader />
        <main className="container grid min-h-[70vh] place-items-center">
          <div className="flex items-center gap-3 text-muted-foreground">
            <Loader2 className="size-5 animate-spin" /> Loading analysis…
          </div>
        </main>
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="min-h-dvh">
        <SiteHeader />
        <main className="container grid min-h-[70vh] place-items-center">
          <div className="flex max-w-sm flex-col items-center gap-4 text-center">
            <span className="grid size-12 place-items-center rounded-full bg-danger/10 text-danger">
              <AlertTriangle className="size-6" />
            </span>
            <h1 className="font-display text-xl font-semibold">Couldn’t load analysis</h1>
            <p className="text-sm text-muted-foreground">{state.message}</p>
            <Button onClick={() => router.push("/")}>Upload a new video</Button>
          </div>
        </main>
      </div>
    );
  }

  const { result } = state;
  const hasFrames = result.frame_angles.length > 0;

  return (
    <div className="min-h-dvh">
      <SiteHeader right={<Downloads result={result} />} />
      <main className="container py-6">
        <ScoreSummary result={result} />

        {/* Full-width video at the top. */}
        {result.has_video ? (
          <VideoPanel result={result} query={query} />
        ) : (
          <div className="mt-6 rounded-lg border border-border bg-surface p-6 text-sm text-muted-foreground">
            No annotated video is available for this analysis. The data
            sections remain fully usable.
          </div>
        )}

        {/* Frame inspector + gait events + per-frame angles, then analytics.
            Angles / contact frames / graphs / stride come first; the form
            problems and score breakdown sit at the end. */}
        <div className="mt-2 flex flex-col gap-6">
          {hasFrames ? (
            <>
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                <FrameControls />
                <ContactNav query={query} setQuery={setQuery} />
                <PerFrameReadout />
              </div>
              <ContactMethodSelect
                value={contactMethod}
                onChange={onMethodChange}
                loading={methodLoading}
              />
              <AngleCharts result={result} />
              <StrideTimeline result={result} />
              <AngleTable result={result} />
              <Asymmetry result={result} />
              <TopProblems result={result} />
              <FormProblems result={result} />
            </>
          ) : (
            <div className="rounded-lg border border-border bg-surface p-8 text-center text-sm text-muted-foreground">
              No per-frame data was produced for this clip. Try a longer, clear
              side-view recording.
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
