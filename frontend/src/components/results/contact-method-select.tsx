"use client";

import { Loader2 } from "lucide-react";
import { Select } from "@/components/ui/select";
import { Section } from "./section";
import {
  CONTACT_METHOD_OPTIONS,
  type ContactMethod,
} from "@/lib/types";

export function ContactMethodSelect({
  value,
  onChange,
  loading,
}: {
  value: ContactMethod;
  onChange: (m: ContactMethod) => void;
  loading: boolean;
}) {
  const active = CONTACT_METHOD_OPTIONS.find((o) => o.value === value);

  return (
    <Section
      title="Contact detection method"
      description="Pick how the initial-contact frame is placed. Angle ratings, strides and form problems recompute instantly; the annotated video keeps the default overlay."
    >
      <div className="flex flex-wrap items-center gap-3">
        <Select
          value={value}
          disabled={loading}
          onChange={(e) => onChange(e.target.value as ContactMethod)}
          aria-label="Initial-contact detection method"
        >
          {CONTACT_METHOD_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
        {loading && (
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" /> Recomputing…
          </span>
        )}
        {active && (
          <p className="text-xs text-muted-foreground">{active.hint}</p>
        )}
      </div>
    </Section>
  );
}
