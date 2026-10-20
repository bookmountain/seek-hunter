import { FLEXIBLE_TYPES, WORK_TYPE_CAPS } from "@/lib/format";
import type { WorkType } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Small-caps mono label. Flexible work (visa-friendly) is a blue outlined tag; full-time is plain ink.
 * Stated hours over the visa limit cancel the flexible styling; a police check gets its own tag.
 */
export function WorkTypeLabel({
  type,
  hours,
  policeCheck,
  className,
}: {
  type: WorkType;
  hours?: boolean;
  policeCheck?: boolean;
  className?: string;
}) {
  const flexible = FLEXIBLE_TYPES.has(type) && !hours;
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-x-1.5 gap-y-1", className)}>
      <span
        className={cn(
          "kicker border px-1.5 py-[2px] leading-none whitespace-nowrap",
          flexible ? "border-blue text-blue" : type === "unknown" ? "border-transparent text-ink-muted" : "border-transparent text-ink",
        )}
      >
        {WORK_TYPE_CAPS[type]}
      </span>
      {hours && (
        <span
          className="kicker bg-chip px-1.5 py-[3px] leading-none whitespace-nowrap text-ink"
          title="The ad states more than 24 hours a week (48 per fortnight), the student visa limit during study"
        >
          Over 24h/wk
        </span>
      )}
      {policeCheck && (
        <span className="kicker bg-chip px-1.5 py-[3px] leading-none whitespace-nowrap text-ink" title="Requires a National Police Check before an offer">
          Police check
        </span>
      )}
    </span>
  );
}
