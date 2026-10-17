import { cn } from "@/lib/utils";

export type ScoreBand = "high" | "mid" | "low";

export const scoreBand = (score: number): ScoreBand => (score >= 75 ? "high" : score >= 55 ? "mid" : "low");

const BAND_CLASS: Record<ScoreBand, string> = {
  high: "text-blue",
  mid: "text-ink",
  low: "text-ink-low",
};

/** Tabular mono numeral coloured by band: >=75 accent blue, 55-74 ink, <55 grey. */
export function Score({ score, className }: { score: number; className?: string }) {
  const band = scoreBand(score);
  return (
    <span
      data-band={band}
      aria-label={`Score ${score}`}
      className={cn("num inline-block leading-none font-medium tracking-[-0.04em]", BAND_CLASS[band], className)}
    >
      {score}
    </span>
  );
}
