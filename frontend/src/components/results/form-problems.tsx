"use client";

import * as React from "react";
import type { AnalysisResult, Severity, Tier } from "@/lib/types";
import { severityRank, tierRank } from "@/lib/format";
import { Section } from "./section";
import { ProblemCard } from "./problem-card";
import { Select } from "@/components/ui/select";

type SortKey = "severity" | "tier" | "occurrence";

export function FormProblems({ result }: { result: AnalysisResult }) {
  const problems = result.form_analysis.problems;
  const [severityFilter, setSeverityFilter] = React.useState<Severity | "all">("all");
  const [tierFilter, setTierFilter] = React.useState<Tier | "all">("all");
  const [sort, setSort] = React.useState<SortKey>("severity");

  const categories = React.useMemo(
    () => Array.from(new Set(problems.map((p) => p.category).filter(Boolean))) as string[],
    [problems]
  );
  const [category, setCategory] = React.useState<string>("all");

  const filtered = React.useMemo(() => {
    let list = problems.filter(
      (p) =>
        (severityFilter === "all" || p.severity === severityFilter) &&
        (tierFilter === "all" || p.tier === tierFilter) &&
        (category === "all" || p.category === category)
    );
    list = [...list].sort((a, b) => {
      if (sort === "severity")
        return severityRank[b.severity] - severityRank[a.severity] || b.occurrence_pct - a.occurrence_pct;
      if (sort === "tier")
        return tierRank[b.tier] - tierRank[a.tier] || severityRank[b.severity] - severityRank[a.severity];
      return b.occurrence_pct - a.occurrence_pct;
    });
    return list;
  }, [problems, severityFilter, tierFilter, category, sort]);

  const counted = filtered.filter((p) => p.tier !== "isolated");
  const isolated = filtered.filter((p) => p.tier === "isolated");

  return (
    <Section
      title="Form problems"
      description={`${problems.length} detected · filter & sort below`}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Select value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value as Severity | "all")} aria-label="Filter by severity">
            <option value="all">All severities</option>
            <option value="severe">Severe</option>
            <option value="moderate">Moderate</option>
            <option value="mild">Mild</option>
          </Select>
          <Select value={tierFilter} onChange={(e) => setTierFilter(e.target.value as Tier | "all")} aria-label="Filter by tier">
            <option value="all">All tiers</option>
            <option value="consistent">Consistent</option>
            <option value="intermittent">Intermittent</option>
            <option value="isolated">Isolated</option>
          </Select>
          {categories.length > 0 && (
            <Select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Filter by category">
              <option value="all">All categories</option>
              {categories.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </Select>
          )}
          <Select value={sort} onChange={(e) => setSort(e.target.value as SortKey)} aria-label="Sort by">
            <option value="severity">Sort: severity</option>
            <option value="tier">Sort: tier</option>
            <option value="occurrence">Sort: frequency</option>
          </Select>
        </div>
      }
    >
      {filtered.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          No problems match these filters.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {counted.map((p) => (
            <ProblemCard key={p.problem_id} problem={p} />
          ))}

          {isolated.length > 0 && (
            <div className="mt-2">
              <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                <span className="h-px flex-1 bg-border" />
                Isolated · low confidence, not scored
                <span className="h-px flex-1 bg-border" />
              </div>
              <div className="flex flex-col gap-3">
                {isolated.map((p) => (
                  <ProblemCard key={p.problem_id} problem={p} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Section>
  );
}
