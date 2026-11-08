"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * A single-choice segmented control (radio-group semantics).
 *
 * Use this instead of Tabs when the buttons switch a setting rather than show different
 * panels: Tabs promise an associated tabpanel (aria-controls), which assistive tech then
 * fails to find. Arrow keys move the selection; the group is a single Tab stop.
 */
type Ctx = { value: string; select: (v: string) => void };
const SegmentedContext = React.createContext<Ctx | null>(null);

export function Segmented({
  value,
  onValueChange,
  label,
  className,
  children,
}: {
  value: string;
  onValueChange: (value: string) => void;
  label: string;
  className?: string;
  children: React.ReactNode;
}) {
  function onKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    const step = ({ ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 } as Record<string, number>)[e.key];
    if (!step) return;
    const buttons = [...e.currentTarget.querySelectorAll<HTMLButtonElement>('[role="radio"]:not(:disabled)')];
    if (!buttons.length) return;
    e.preventDefault();
    const current = buttons.findIndex((b) => b.dataset.value === value);
    const next = buttons[(current + step + buttons.length) % buttons.length]!;
    onValueChange(next.dataset.value!);
    next.focus();
  }
  return (
    <SegmentedContext.Provider value={{ value, select: onValueChange }}>
      <div
        role="radiogroup"
        aria-label={label}
        onKeyDown={onKeyDown}
        className={cn("inline-flex min-h-9 max-w-full flex-wrap items-center gap-1 rounded-lg bg-muted p-1 text-muted-foreground", className)}
      >
        {children}
      </div>
    </SegmentedContext.Provider>
  );
}

export function SegmentedItem({ value, className, children }: { value: string; className?: string; children: React.ReactNode }) {
  const ctx = React.useContext(SegmentedContext);
  if (!ctx) throw new Error("SegmentedItem must be inside Segmented");
  const checked = ctx.value === value;
  return (
    <button
      type="button"
      role="radio"
      aria-checked={checked}
      tabIndex={checked ? 0 : -1}
      data-value={value}
      data-state={checked ? "active" : "inactive"}
      onClick={() => ctx.select(value)}
      className={cn(
        "inline-flex h-7 items-center justify-center gap-1.5 rounded-md px-3 text-xs font-medium whitespace-nowrap transition-all outline-none focus-visible:ring-[3px] focus-visible:ring-ring disabled:opacity-50 data-[state=active]:bg-background-elevated data-[state=active]:text-foreground data-[state=active]:shadow-sm",
        className,
      )}
    >
      {children}
    </button>
  );
}
