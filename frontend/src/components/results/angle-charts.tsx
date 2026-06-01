"use client";

import * as React from "react";
import * as RC from "recharts";

// Recharts v3 ships very strict JSX prop typings for its declarative parts;
// alias to `any` so the readable chart markup below doesn't fight the overloads.
const LineChart = RC.LineChart as any;
const Line = RC.Line as any;
const XAxis = RC.XAxis as any;
const YAxis = RC.YAxis as any;
const CartesianGrid = RC.CartesianGrid as any;
const ResponsiveContainer = RC.ResponsiveContainer as any;
const ReferenceArea = RC.ReferenceArea as any;
const ReferenceLine = RC.ReferenceLine as any;
const RTooltip = RC.Tooltip as any;
import type { AnalysisResult } from "@/lib/types";
import { useAnalysis } from "@/store/useAnalysis";
import { downsample } from "@/lib/data";
import { angleBase, formatMs, SERIES_COLORS } from "@/lib/format";
import { Section } from "./section";
import { Select } from "@/components/ui/select";
import { cn } from "@/lib/utils";

const BASES = [
  { key: "knee_flexion", label: "Knee flexion" },
  { key: "hip_flexion", label: "Hip flexion" },
  { key: "ankle_dorsiflexion", label: "Ankle dorsiflexion" },
  { key: "arm_swing", label: "Arm swing" },
  { key: "arm_drive", label: "Arm drive" },
  { key: "trunk_lean", label: "Trunk lean" },
] as const;

type Row = { frame: number; ms: number; left?: number; right?: number; value?: number };

export function AngleCharts({ result }: { result: AnalysisResult }) {
  const index = useAnalysis((s) => s.index);
  const currentFrame = useAnalysis((s) => s.currentFrame);
  const seekToFrame = useAnalysis((s) => s.seekToFrame);

  const [base, setBase] = React.useState<string>("knee_flexion");
  const [showLeft, setShowLeft] = React.useState(true);
  const [showRight, setShowRight] = React.useState(true);
  const [showMarkers, setShowMarkers] = React.useState(true);

  const isBilateral = base !== "trunk_lean";
  const color = SERIES_COLORS[base] ?? "#A3E635";

  const data = React.useMemo<Row[]>(() => {
    if (!index) return [];
    if (!isBilateral) {
      return downsample(index.series["trunk_lean"] ?? []).map((p) => ({
        frame: p.frame, ms: p.ms, value: p.value,
      }));
    }
    const left = index.series[`left_${base}`] ?? [];
    const right = index.series[`right_${base}`] ?? [];
    const map = new Map<number, Row>();
    for (const p of left) map.set(p.frame, { frame: p.frame, ms: p.ms, left: p.value });
    for (const p of right) {
      const r = map.get(p.frame);
      if (r) r.right = p.value;
      else map.set(p.frame, { frame: p.frame, ms: p.ms, right: p.value });
    }
    const merged = Array.from(map.values()).sort((a, b) => a.frame - b.frame);
    // simple stride downsample over merged rows (keeps endpoints)
    const MAX = 800;
    if (merged.length <= MAX) return merged;
    const step = merged.length / MAX;
    const out: Row[] = [];
    for (let i = 0; i < MAX; i++) out.push(merged[Math.floor(i * step)]);
    out[out.length - 1] = merged[merged.length - 1];
    return out;
  }, [index, base, isBilateral]);

  const summaryRow = React.useMemo(
    () =>
      result.summary.find((s) => s.name === (isBilateral ? `left_${base}` : "trunk_lean")) ??
      result.summary.find((s) => angleBase(s.name) === base),
    [result.summary, base, isBilateral]
  );
  const hasBand = summaryRow?.min_threshold != null && summaryRow?.max_threshold != null;

  const contacts = React.useMemo(
    () => (index ? index.eventsByPhase.initial_contact : []),
    [index]
  );

  if (!index) return null;

  return (
    <Section
      title="Angle over time"
      description="Click a point to jump the video there. Optimal range shaded where available."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Select value={base} onChange={(e) => setBase(e.target.value)} aria-label="Choose angle">
            {BASES.map((b) => (
              <option key={b.key} value={b.key}>{b.label}</option>
            ))}
          </Select>
        </div>
      }
    >
      {/* Series toggles */}
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
        {isBilateral ? (
          <>
            <Toggle active={showLeft} onClick={() => setShowLeft((v) => !v)} color="#A3E635">
              Left
            </Toggle>
            <Toggle active={showRight} onClick={() => setShowRight((v) => !v)} color="#FB923C">
              Right
            </Toggle>
          </>
        ) : (
          <span className="text-muted-foreground">Midline value (single series)</span>
        )}
        <Toggle active={showMarkers} onClick={() => setShowMarkers((v) => !v)} color="rgb(var(--muted))">
          Foot strikes
        </Toggle>
      </div>

      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={data}
            margin={{ top: 8, right: 12, bottom: 4, left: -8 }}
            onClick={(e: any) => {
              const f = e?.activeLabel;
              if (typeof f === "number") seekToFrame(f);
            }}
          >
            <CartesianGrid stroke="rgb(var(--border))" strokeOpacity={0.4} vertical={false} />
            <XAxis
              dataKey="frame"
              type="number"
              domain={["dataMin", "dataMax"]}
              tick={{ fill: "rgb(var(--muted))", fontSize: 11 }}
              stroke="rgb(var(--border))"
              tickFormatter={(v: number) => String(v)}
            />
            <YAxis
              tick={{ fill: "rgb(var(--muted))", fontSize: 11 }}
              stroke="rgb(var(--border))"
              width={44}
              tickFormatter={(v: number) => `${v}°`}
            />

            {hasBand && (
              <ReferenceArea
                y1={summaryRow!.min_threshold!}
                y2={summaryRow!.max_threshold!}
                fill="rgb(var(--success))"
                fillOpacity={0.08}
                stroke="rgb(var(--success))"
                strokeOpacity={0.25}
                strokeDasharray="3 3"
              />
            )}

            {showMarkers &&
              contacts.map((ev) => (
                <ReferenceLine
                  key={`${ev.frame_number}-${ev.side}`}
                  x={ev.frame_number}
                  stroke={ev.side === "left" ? "#A3E635" : "#FB923C"}
                  strokeOpacity={0.25}
                  strokeWidth={1}
                />
              ))}

            {/* current-frame cursor */}
            <ReferenceLine x={currentFrame} stroke="rgb(var(--foreground))" strokeOpacity={0.6} strokeWidth={1.5} />

            <RTooltip
              cursor={{ stroke: "rgb(var(--primary))", strokeOpacity: 0.4 }}
              contentStyle={{
                background: "rgb(var(--surface-2))",
                border: "1px solid rgb(var(--border))",
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: "rgb(var(--muted))" }}
              labelFormatter={(f: number) => `Frame ${f} · ${formatMs((Number(f) / index.fps) * 1000)}`}
              formatter={(val: any, name: any) => [`${Number(val).toFixed(1)}°`, name]}
            />

            {isBilateral ? (
              <>
                {showLeft && (
                  <Line type="monotone" dataKey="left" name="Left" stroke="#A3E635" dot={false} strokeWidth={1.75} isAnimationActive={false} connectNulls />
                )}
                {showRight && (
                  <Line type="monotone" dataKey="right" name="Right" stroke="#FB923C" dot={false} strokeWidth={1.75} isAnimationActive={false} connectNulls />
                )}
              </>
            ) : (
              <Line type="monotone" dataKey="value" name="Trunk lean" stroke={color} dot={false} strokeWidth={1.75} isAnimationActive={false} connectNulls />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Section>
  );
}

function Toggle({
  active, onClick, color, children,
}: {
  active: boolean;
  onClick: () => void;
  color: string;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 transition-colors",
        active ? "border-border bg-surface-2 text-foreground" : "border-border bg-transparent text-muted-foreground opacity-60"
      )}
    >
      <span className="inline-block size-2 rounded-full" style={{ background: color }} />
      {children}
    </button>
  );
}
