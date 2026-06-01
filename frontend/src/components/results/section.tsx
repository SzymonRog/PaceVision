import * as React from "react";
import { cn } from "@/lib/utils";

export function Section({
  title,
  description,
  actions,
  children,
  className,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn("rounded-lg border border-border bg-surface", className)}
      aria-label={title}
    >
      <header className="flex flex-wrap items-end justify-between gap-3 border-b border-border p-4">
        <div>
          <h2 className="font-display text-base font-semibold tracking-tight">{title}</h2>
          {description && (
            <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
          )}
        </div>
        {actions}
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}
