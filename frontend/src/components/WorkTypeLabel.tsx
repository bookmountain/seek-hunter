import { FLEXIBLE_TYPES, WORK_TYPE_CAPS } from "@/lib/format";
import type { WorkType } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Small-caps mono label. Flexible work (visa-friendly) is a blue outlined tag; full-time is plain ink. */
export function WorkTypeLabel({ type, hours, className }: { type: WorkType; hours?: boolean; className?: string }) {
  const flexible = FLEXIBLE_TYPES.has(type);
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
        <span className="kicker bg-chip px-1.5 py-[3px] leading-none whitespace-nowrap text-ink" title="Stated hours may exceed the visa work limit">
          Hours?
        </span>
      )}
    </span>
  );
}
