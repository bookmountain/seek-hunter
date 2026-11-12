import { SectionHead } from "@/components/PageHead";
import { Button } from "@/components/ui/button";
import {
  balance,
  blendLabel,
  splitOf,
  splitTotal,
  weightProblems,
  type ScoringValue,
  withWorkMax,
} from "@/lib/scoring";
import type { Weights } from "@/lib/types";
import { cn } from "@/lib/utils";

const int0 = (v: string): number => Math.max(0, Math.trunc(Number(v) || 0));

/** Small mono number box with an optional unit after it. */
function NumBox({
  id,
  label,
  value,
  onChange,
  unit,
  max,
  size = "sm",
}: {
  id: string;
  label: string;
  value: number;
  onChange: (n: number) => void;
  unit?: string;
  max?: number;
  size?: "sm" | "lg";
}) {
  return (
    <span className="inline-flex items-baseline gap-1">
      <input
        id={id}
        aria-label={label}
        type="number"
        inputMode="numeric"
        min={0}
        max={max}
        step={1}
        value={value}
        onChange={(e) => onChange(max === undefined ? int0(e.target.value) : Math.min(max, int0(e.target.value)))}
        className={cn(
          "field num text-right outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none",
          size === "lg" ? "h-11 w-[4.5rem] px-2 text-[26px] leading-none" : "h-8 w-14 px-1.5 text-[14px]",
        )}
      />
      {unit && <span className={cn("num text-ink-muted", size === "lg" ? "text-[18px]" : "text-[13px]")}>{unit}</span>}
    </span>
  );
}

const PARTS = [
  { key: "work", no: "01", name: "Work type", tone: "bg-ink" },
  { key: "skill", no: "02", name: "Skill match", tone: "bg-blue" },
  { key: "role", no: "03", name: "Role fit", tone: "bg-ink-low" },
] as const;

export function ScoringSection({
  value,
  onChange,
  llmEnabled,
  dirty,
  pendingRescore,
  onRescore,
  rescoring,
}: {
  value: ScoringValue;
  onChange: (v: ScoringValue) => void;
  llmEnabled: boolean;
  /** Scoring differs from what's saved. */
  dirty: boolean;
  /** Scoring was just saved with changes, so stored jobs are out of date. */
  pendingRescore: boolean;
  onRescore: () => void;
  rescoring: boolean;
}) {
  const { weights: w, workMax, ruleBlend } = value;
  const split = splitOf(w, workMax);
  const total = splitTotal(split);
  const problems = weightProblems(w, workMax);
  const setW = (patch: Partial<Weights>) => onChange({ ...value, weights: { ...w, ...patch } });
  const setPart = (key: (typeof PARTS)[number]["key"], n: number) => {
    if (key === "work") onChange({ ...value, workMax: n, weights: withWorkMax(w, workMax, n) });
    else setW(key === "skill" ? { skill_max: n } : { role_max: n });
  };
  const doBalance = () => {
    const b = balance(split);
    onChange({ ...value, workMax: b.work, weights: { ...withWorkMax(w, workMax, b.work), skill_max: b.skill, role_max: b.role } });
  };
  const perSkill = w.skill_saturation > 0 ? w.skill_max / w.skill_saturation : 0;
  const rulesPct = Math.round(ruleBlend * 100);

  return (
    <section className="mt-12" aria-labelledby="scoring-head">
      <SectionHead>
        <span id="scoring-head">Scoring</span>
      </SectionHead>
      <p className="mt-3 max-w-3xl text-[14.5px] leading-relaxed text-ink-muted">
        Every job gets a rule score out of 100, built from three parts. Set how much of the 100 each part is worth.
      </p>

      {/* The 100-point bar */}
      <div className="mt-6 grid gap-x-10 gap-y-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
        <div>
          <div
            className="relative flex h-3 w-full overflow-hidden border border-ink"
            role="img"
            aria-label={`Rule score split: work type ${split.work}%, skill match ${split.skill}%, role fit ${split.role}%`}
          >
            {PARTS.map((p) => {
              const pct = total > 0 ? (split[p.key] / Math.max(total, 100)) * 100 : 0;
              return <span key={p.key} className={cn("h-full border-r border-white last:border-r-0", p.tone)} style={{ width: `${pct}%` }} />;
            })}
          </div>
          <div className="num mt-1.5 flex justify-between text-[10.5px] text-ink-low">
            <span>0</span>
            <span>50</span>
            <span>100</span>
          </div>
        </div>
        <div className="flex items-baseline gap-3 md:justify-end" aria-live="polite">
          <span className="kicker text-ink-muted">Total</span>
          <span data-testid="weights-total" className={cn("num text-[32px] leading-none font-medium", total === 100 ? "text-ink" : "text-blue")}>
            {total}%
          </span>
          {total !== 100 && (
            <>
              <span className="num text-[12px] text-ink-muted">{total > 100 ? `${total - 100} over` : `${100 - total} short`}</span>
              <Button size="sm" variant="outline" onClick={doBalance}>
                Balance to 100
              </Button>
            </>
          )}
        </div>
      </div>

      {problems.length > 0 && (
        <div role="alert" className="mt-4 border-l-2 border-blue bg-selected px-3 py-2 text-[13.5px]">
          {problems.map((p) => (
            <p key={p}>{p}</p>
          ))}
          <p className="text-ink-muted">Settings can't be saved until this is fixed.</p>
        </div>
      )}

      {/* The three parts */}
      <div className="mt-6 grid border-t border-ink md:grid-cols-3">
        {PARTS.map((p) => (
          <div key={p.key} className="border-b border-rule py-5 md:border-b-0 md:border-l md:px-6 md:first:border-l-0 md:first:pl-0">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="kicker flex items-center gap-2 text-ink-muted">
                  <span aria-hidden className={cn("size-2", p.tone)} />
                  {p.no}
                </p>
                <h3 className="display mt-1.5 text-[19px] leading-tight">{p.name}</h3>
              </div>
              <NumBox id={`part-${p.key}`} label={`${p.name} share of the rule score`} value={split[p.key]} onChange={(n) => setPart(p.key, n)} unit="%" max={100} size="lg" />
            </div>

            {p.key === "work" && (
              <>
                <p className="mt-2 text-[13.5px] text-ink-muted">Points for the kind of job. Each type earns part of the {workMax}.</p>
                <dl className="mt-4 divide-y divide-rule border-y border-rule text-[13.5px]">
                  {(
                    [
                      ["flexible_work", "Contract, part-time, casual"],
                      ["full_time", "Full-time"],
                    ] as const
                  ).map(([k, label]) => (
                    <div key={k} className="flex items-center justify-between gap-3 py-2">
                      <dt>{label}</dt>
                      <dd className="flex items-baseline gap-1.5 whitespace-nowrap">
                        <span className="text-ink-muted">earns</span>
                        <NumBox id={`w-${k}`} label={`${label} points`} value={w[k]} max={workMax} onChange={(n) => setW({ [k]: n })} />
                        <span className="num text-ink-muted">of {workMax}</span>
                      </dd>
                    </div>
                  ))}
                </dl>
                <p className="mt-2 text-[12.5px] text-ink-muted">Ads stating hours over the visa limit count as full-time.</p>
              </>
            )}

            {p.key === "skill" && (
              <>
                <p className="mt-2 text-[13.5px] text-ink-muted">Your resume skills that appear in the ad.</p>
                <dl className="mt-4 divide-y divide-rule border-y border-rule text-[13.5px]">
                  <div className="flex items-center justify-between gap-3 py-2">
                    <dt>Full marks at</dt>
                    <dd className="flex items-baseline gap-1.5 whitespace-nowrap">
                      <NumBox id="w-skill_saturation" label="Matched skills for full marks" value={w.skill_saturation} onChange={(n) => setW({ skill_saturation: n })} />
                      <span className="text-ink-muted">skills</span>
                    </dd>
                  </div>
                  <div className="flex items-center justify-between gap-3 py-2">
                    <dt className="text-ink-muted">Each matched skill</dt>
                    <dd className="num">{perSkill ? `${perSkill.toFixed(1)} pts` : "–"}</dd>
                  </div>
                </dl>
              </>
            )}

            {p.key === "role" && (
              <>
                <p className="mt-2 text-[13.5px] text-ink-muted">How well the job title fits, from the boost and penalty term lists below.</p>
                <dl className="mt-4 divide-y divide-rule border-y border-rule text-[13.5px]">
                  {(
                    [
                      ["Title has a boost term", w.role_max],
                      ["Neutral title", Math.floor(w.role_max / 3)],
                      ["Penalty term or 10+ years", 0],
                    ] as const
                  ).map(([label, pts]) => (
                    <div key={label} className="flex items-center justify-between gap-3 py-2">
                      <dt>{label}</dt>
                      <dd className="num whitespace-nowrap">
                        {pts} <span className="text-ink-muted">of {w.role_max}</span>
                      </dd>
                    </div>
                  ))}
                </dl>
              </>
            )}
          </div>
        ))}
      </div>

      {/* Rules vs AI */}
      <div className="mt-8 grid gap-x-10 gap-y-4 border-t border-ink pt-5 md:grid-cols-[16rem_minmax(0,1fr)]">
        <div>
          <h3 className="display text-[19px] leading-tight">Rules vs AI</h3>
          <p className="mt-1.5 text-[13.5px] text-ink-muted">
            The final score mixes the rule score with the AI's own 0–100 fit score. Jobs the AI didn't score use the rule score alone. Default 60 / 40.
          </p>
        </div>
        <div className={cn(!llmEnabled && "opacity-60")}>
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <p className="num text-[22px] leading-none" data-testid="blend-label">
              <span className="text-ink">{rulesPct}% rules</span>
              <span className="text-ink-faint"> / </span>
              <span className="text-blue">{100 - rulesPct}% AI</span>
            </p>
            <span className="inline-flex items-baseline gap-1.5 text-[13px] text-ink-muted">
              Rules share
              <NumBox id="rule-blend-num" label="Rules share of the final score, percent" value={rulesPct} max={100} unit="%" onChange={(n) => onChange({ ...value, ruleBlend: n / 100 })} />
            </span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={rulesPct}
            aria-label="Rules vs AI blend"
            aria-valuetext={blendLabel(ruleBlend)}
            onChange={(e) => onChange({ ...value, ruleBlend: Number(e.target.value) / 100 })}
            className="range mt-4 w-full"
            style={{ ["--fill" as string]: `${rulesPct}%` }}
          />
          <div className="kicker mt-1 flex justify-between text-[10px] text-ink-muted">
            <span>All AI</span>
            <span>All rules</span>
          </div>
          {!llmEnabled && <p className="mt-2 text-[13px] text-ink-muted">AI scoring is switched off, so every score is the rule score for now.</p>}
        </div>
      </div>

      {/* Rescore */}
      <div
        className={cn(
          "mt-8 flex flex-wrap items-center justify-between gap-x-6 gap-y-3 border-y px-0 py-3 text-[13.5px]",
          pendingRescore ? "border-blue" : "border-rule",
        )}
        role={pendingRescore ? "status" : undefined}
      >
        <p className={pendingRescore ? "text-ink" : "text-ink-muted"}>
          {pendingRescore
            ? "Saved. Jobs already in the list still have their old scores."
            : dirty
              ? "Unsaved scoring changes. Once saved they apply to new jobs; existing jobs keep their scores until rescored."
              : "Scoring changes apply to new jobs. Existing jobs keep their scores until rescored."}{" "}
          <span className="text-ink-muted">Rescoring covers the last 7 days, keeps each job's AI score and sends nothing.</span>
        </p>
        <Button size="sm" variant={pendingRescore ? "default" : "outline"} onClick={onRescore} disabled={rescoring || dirty}>
          {rescoring ? "Starting…" : "Rescore last 7 days"}
        </Button>
      </div>
    </section>
  );
}
