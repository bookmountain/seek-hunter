import { cn } from "@/lib/utils";

export function ScoreBadge({ score }: { score: number }) {
  const tone =
    score >= 75
      ? "bg-emerald-600 text-white"
      : score >= 55
        ? "bg-amber-500 text-white"
        : "bg-muted text-muted-foreground";
  return (
    <span className={cn("inline-flex h-7 w-10 items-center justify-center rounded-md text-sm font-semibold", tone)}>
      {score}
    </span>
  );
}
