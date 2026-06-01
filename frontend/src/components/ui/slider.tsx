"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/** Lightweight single-value slider built on a native range input. */
export interface SliderProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange" | "value"> {
  value: number;
  onValueChange: (v: number) => void;
}

export function Slider({
  value,
  onValueChange,
  min = 0,
  max = 100,
  step = 1,
  className,
  ...props
}: SliderProps) {
  const pct =
    ((value - Number(min)) / (Number(max) - Number(min) || 1)) * 100;
  return (
    <input
      type="range"
      value={value}
      min={min}
      max={max}
      step={step}
      onChange={(e) => onValueChange(Number(e.target.value))}
      className={cn(
        "h-2 w-full cursor-pointer appearance-none rounded-full bg-surface-2 accent-primary",
        "[&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-primary",
        className
      )}
      style={{
        background: `linear-gradient(to right, rgb(var(--primary)) ${pct}%, rgb(var(--surface-2)) ${pct}%)`,
      }}
      {...props}
    />
  );
}
