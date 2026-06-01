"use client";

import * as React from "react";
import { CheckCircle2 } from "lucide-react";
import type { AnalysisResult } from "@/lib/types";
import { severityRank, tierRank } from "@/lib/format";
import { Section } from "./section";
import { ProblemCard } from "./problem-card";

export function TopProblems({ result }: { result: AnalysisResult }) {
  const problems = result.form_analysis.problems;

  const top = React.useMemo(() => {
    return [...problems]
      .filter((p) => p.tier !== "isolated")
      .sort(
        (a, b) =>
          severityRank[b.severity] - severityRank[a.severity] ||
          tierRank[b.tier] - tierRank[a.tier] ||
          b.occurrence_pct - a.occurrence_pct
      )
      .slice(0, 3);
  }, [problems]);

  return (
    <Section
      title="What to work on"
      description="Your most impactful form issues, in plain language."
    >
      {top.length === 0 ? (
        <div className="flex items-center gap-3 rounded-md border border-success/30 bg-success/10 p-4 text-sm text-success">
          <CheckCircle2 className="size-5 shrink-0" />
          No consistent form problems were flagged. Nice running!
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {top.map((p, i) => (
            <ProblemCard key={p.problem_id} problem={p} defaultOpen={i === 0} />
          ))}
        </div>
      )}
    </Section>
  );
}
