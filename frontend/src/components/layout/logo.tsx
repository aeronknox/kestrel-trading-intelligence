import { cn } from "@/lib/utils";

export function Logo({ className, showText = true }: { className?: string; showText?: boolean }) {
  return (
    <span className={cn("flex items-center gap-2", className)}>
      <svg viewBox="0 0 32 32" className="size-7" aria-hidden>
        <rect width="32" height="32" rx="8" fill="var(--chart-1)" opacity="0.16" />
        <path d="M7 21 L13 14 L17.5 18 L25 9" fill="none" stroke="var(--chart-1)" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="25" cy="9" r="2.2" fill="var(--chart-2)" />
      </svg>
      {showText && (
        <span className="text-[15px] font-semibold tracking-tight">
          Kestrel<span className="text-muted-foreground font-normal"> Intelligence</span>
        </span>
      )}
    </span>
  );
}
