import { FLEXIBLE_TYPES, WORK_TYPE_CAPS } from "@/lib/format";
import type { WorkType } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Small-caps mono label. Flexible work (visa-friendly) is olive and underlined; full-time is plain ink. */
export function WorkTypeLabel({ type, hours, className }: { type: WorkType; hours?: boolean; className?: string }) {
  const flexible = FLEXIBLE_TYPES.has(type);
  return (
    <span className={cn("inline-flex flex-wrap items-baseline gap-x-2 gap-y-1", className)}>
      <span
        className={cn(
          "kicker whitespace-nowrap",
          flexible ? "text-olive underline decoration-olive/70 decoration-1 underline-offset-[3px]" : type === "unknown" ? "text-ink-faint" : "text-ink",
        )}
      >
        {WORK_TYPE_CAPS[type]}
      </span>
      {hours && (
        <span className="kicker whitespace-nowrap text-signal" title="Stated hours may exceed the visa work limit">
          Hours?
        </span>
      )}
    </span>
  );
}
