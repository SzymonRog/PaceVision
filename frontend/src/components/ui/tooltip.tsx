"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/** Minimal hover/focus tooltip — no external dependency. */
export function Tooltip({
  content,
  children,
  side = "top",
  className,
}: {
  content: React.ReactNode;
  children: React.ReactNode;
  side?: "top" | "bottom";
  className?: string;
}) {
  return (
    <span className="group/tt relative inline-flex">
      <span tabIndex={0} className="inline-flex outline-none">
        {children}
      </span>
      <span
        role="tooltip"
        className={cn(
          "pointer-events-none absolute left-1/2 z-50 w-max max-w-xs -translate-x-1/2 scale-95 rounded-md border border-border bg-popover px-2.5 py-1.5 text-xs text-foreground opacity-0 shadow-lg transition-all duration-150 group-hover/tt:scale-100 group-hover/tt:opacity-100 group-focus-within/tt:scale-100 group-focus-within/tt:opacity-100",
          side === "top" ? "bottom-full mb-2" : "top-full mt-2",
          className
        )}
      >
        {content}
      </span>
    </span>
  );
}
