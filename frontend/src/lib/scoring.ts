import type { Weights } from "./types";

/** The three parts of the 100-point rule score (see backend scoring.score_job). The work-type part
 *  is worth as much as the better-paid work type, i.e. max(flexible_work, full_time). */
export interface Split {
  work: number;
  skill: number;
  role: number;
}

export const DEFAULT_WEIGHTS: Weights = { flexible_work: 35, full_time: 10, skill_max: 50, role_max: 15, skill_saturation: 8 };
export const DEFAULT_RULE_BLEND = 0.6;

export const workMaxOf = (w: Weights) => Math.max(w.flexible_work, w.full_time);

export const splitOf = (w: Weights, workMax = workMaxOf(w)): Split => ({ work: workMax, skill: w.skill_max, role: w.role_max });

export const splitTotal = (s: Split) => s.work + s.skill + s.role;

/** Scales the parts to add up to exactly 100 (largest remainder), keeping their proportions. All
 *  zero falls back to the defaults. */
export function balance(s: Split): Split {
  const total = splitTotal(s);
  if (total <= 0) return splitOf(DEFAULT_WEIGHTS);
  const keys: (keyof Split)[] = ["work", "skill", "role"];
  const raw = keys.map((k) => (Math.max(0, s[k]) / total) * 100);
  const out = raw.map(Math.floor);
  let left = 100 - out.reduce((a, b) => a + b, 0);
  const order = raw.map((r, i) => [r - Math.floor(r), i] as const).sort((a, b) => b[0] - a[0]);
  for (const [, i] of order) {
    if (left <= 0) break;
    out[i] += 1;
    left -= 1;
  }
  return { work: out[0], skill: out[1], role: out[2] };
}

/** New work-type maximum: both work types are scaled with it, so their ratio is kept and the one
 *  that earned the full amount still does. */
export function withWorkMax(w: Weights, oldMax: number, newMax: number): Weights {
  if (oldMax <= 0) return { ...w, flexible_work: newMax, full_time: newMax };
  const scale = (v: number) => (v >= oldMax ? newMax : Math.min(newMax, Math.round((v * newMax) / oldMax)));
  return { ...w, flexible_work: scale(w.flexible_work), full_time: scale(w.full_time) };
}

/** Everything that stops these weights from being saved (the server rejects the same things). */
export function weightProblems(w: Weights, workMax: number): string[] {
  const out: string[] = [];
  const total = splitTotal(splitOf(w, workMax));
  if (total !== 100) out.push(`The three parts add up to ${total}%. They must add up to 100%.`);
  if (workMaxOf(w) !== workMax)
    out.push(
      `Neither work type earns the full ${workMax} points, so the work-type part is really worth ${workMaxOf(w)}. ` +
        `Give one of them ${workMax}, or lower the work-type share.`,
    );
  if (w.skill_saturation < 1) out.push("Full skill marks need at least 1 matched skill.");
  if ([w.flexible_work, w.full_time, w.skill_max, w.role_max].some((v) => v < 0)) out.push("Points can't be negative.");
  return out;
}

/** The final-score formula as words, e.g. "60% rules / 40% AI". */
export function blendLabel(ruleBlend: number): string {
  const rules = Math.round(ruleBlend * 100);
  return `${rules}% rules / ${100 - rules}% AI`;
}

export const sameWeights = (a: Weights, b: Weights) =>
  (Object.keys(a) as (keyof Weights)[]).every((k) => a[k] === b[k]);

export interface ScoringValue {
  weights: Weights;
  /** The work-type share; edited on its own so the two work types can be set relative to it. */
  workMax: number;
  ruleBlend: number;
}

export const scoringFrom = (weights: Weights, ruleBlend: number | undefined): ScoringValue => ({
  weights,
  workMax: workMaxOf(weights),
  ruleBlend: ruleBlend ?? DEFAULT_RULE_BLEND,
});
