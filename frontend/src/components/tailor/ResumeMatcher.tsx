import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { CopyButton } from "@/components/CopyButton";
import { Button } from "@/components/ui/button";
import { api, errMsg } from "@/lib/api";
import type { AtsBreakdown, AtsPair, InterviewPrep, InterviewQuestion, ResumeMatcherResult } from "@/lib/types";
import { cn } from "@/lib/utils";

const PARTS: [keyof AtsBreakdown, string, number][] = [
  ["keyword_match", "Keyword match", 40],
  ["skills_coverage", "Skills coverage", 20],
  ["title_alignment", "Title alignment", 15],
  ["section_completeness", "Section completeness", 15],
  ["date_consistency", "Date consistency", 10],
];

const fmt = (n: number | null | undefined) => (n == null ? "—" : String(Math.round(n)));

const rmBusy = (rm?: ResumeMatcherResult | null) => rm?.status === "queued" || rm?.status === "running";

/** Two hairlines per part: current (faint) above tailored (blue). */
function PartBar({ label, weight, before, after }: { label: string; weight: number; before: number | null; after: number | null }) {
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-3 gap-y-1">
      <span className="font-mono text-[11.5px] text-ink">
        {label} <span className="text-ink-muted">· {weight}%</span>
      </span>
      <span className="num text-[11.5px] text-ink-muted">
        {fmt(before)} <span aria-hidden>→</span>
        <span className="sr-only">to</span> <span className="text-ink">{fmt(after)}</span>
      </span>
      <div className="col-span-2 space-y-[3px]" aria-hidden>
        <div className="h-0.5 bg-rule">
          <div className="h-full bg-ink-faint" style={{ width: `${before ?? 0}%` }} />
        </div>
        <div className="h-0.5 bg-rule">
          <div className="h-full bg-blue" style={{ width: `${after ?? 0}%` }} />
        </div>
      </div>
    </li>
  );
}

function Chips({ items }: { items: string[] }) {
  return (
    <ul className="mt-2 flex flex-wrap gap-1.5">
      {items.map((k) => (
        <li key={k} className="border border-chip bg-chip px-2 py-1 font-mono text-[11.5px] leading-none text-ink">
          {k}
        </li>
      ))}
    </ul>
  );
}

function RetryButton({ tid, label = "Retry" }: { tid: number; label?: string }) {
  const qc = useQueryClient();
  const run = useMutation({
    mutationFn: () => api.rerunResumeMatcher(tid),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tailoring", tid] }),
    onError: (e: Error) => toast.error(errMsg(e)),
  });
  return (
    <Button variant="outline" size="sm" onClick={() => run.mutate()} disabled={run.isPending}>
      {run.isPending ? "Starting…" : label}
    </Button>
  );
}

/** Where Resume-Matcher stands for this run: disabled / needs sign-in, running, failed, or a done summary. */
export function ResumeMatcherStatusLine({ tid, rm }: { tid: number; rm: ResumeMatcherResult | null | undefined }) {
  const needHealth = !rm || rm.status === "unavailable";
  const { data: health } = useQuery({
    queryKey: ["resume-matcher-status"],
    queryFn: api.resumeMatcherStatus,
    enabled: needHealth,
    staleTime: 30_000,
  });

  if (rmBusy(rm)) {
    return (
      <div className="mt-4" aria-label="Resume-Matcher progress">
        <p className="font-mono text-[12.5px]" role="status" aria-live="polite">
          <span className="text-blue">{rm!.status === "queued" ? "QUEUED" : "RUNNING"}</span>
          <span className="text-ink-muted"> · </span>Analysing with Resume-Matcher
        </p>
        <div className="relative mt-2 h-0.5 overflow-hidden bg-rule" aria-hidden>
          <div className="indeterminate absolute inset-y-0 w-1/3 bg-blue" />
        </div>
        <p className="mt-2 text-[12.5px] text-ink-muted">Its AI rewrite, interview prep and outreach take a few minutes.</p>
      </div>
    );
  }
  if (rm?.status === "failed") {
    return (
      <div className="mt-4">
        <p className="kicker text-ink">Resume-Matcher failed</p>
        <pre className="mt-2 overflow-x-auto bg-chip px-3 py-2 font-mono text-[11.5px] whitespace-pre-wrap text-ink">{rm.error || "Unknown error"}</pre>
        <div className="mt-2">
          <RetryButton tid={tid} />
        </div>
      </div>
    );
  }
  if (needHealth) {
    const enabled = health?.enabled ?? false;
    const signIn = enabled && health?.reachable && !health.llm_configured;
    return (
      <div className="mt-4 bg-chip px-3 py-2.5 text-[12.5px] leading-relaxed text-ink-muted" data-testid="rm-note">
        {!health ? (
          "Checking Resume-Matcher…"
        ) : !enabled ? (
          <>Resume-Matcher is off. Set RM_BASE_URL on the server to add its AI rewrite, interview prep and outreach.</>
        ) : !health.reachable ? (
          <>Resume-Matcher is unreachable{health.error ? `: ${health.error}` : "."}</>
        ) : signIn || rm?.status === "unavailable" ? (
          <>
            Resume-Matcher needs ChatGPT sign-in.{" "}
            {health.settings_url && (
              <a href={health.settings_url} target="_blank" rel="noreferrer" className="text-blue underline">
                Open its settings
              </a>
            )}
            , sign in, then run it.
          </>
        ) : (
          <>Resume-Matcher has not analysed this run yet.</>
        )}
        {enabled && health?.reachable && (
          <div className="mt-2">
            <RetryButton tid={tid} label="Run Resume-Matcher" />
          </div>
        )}
      </div>
    );
  }
  if (rm?.status === "done") {
    return (
      <p className="num mt-4 text-[11.5px] text-ink-muted">
        Resume-Matcher's own AI rewrite scores {fmt(rm.ats_score)}
        {rm.rm_url && (
          <>
            {" · "}
            <a href={rm.rm_url} target="_blank" rel="noreferrer" className="text-blue hover:underline">
              Open in Resume-Matcher
            </a>
          </>
        )}
      </p>
    );
  }
  return null;
}

/** "ATS 62 → 81": Resume-Matcher's formula on the current vs tailored resume, with its 5 weighted parts. */
export function AtsBlock({ ats, tid, rm }: { ats?: AtsPair; tid: number; rm?: ResumeMatcherResult | null }) {
  const cur = ats?.current ?? null;
  const tl = ats?.tailored ?? null;
  return (
    <section aria-labelledby="ats-title" className="mt-6 grid gap-x-10 gap-y-5 border-b border-rule pb-6 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)_minmax(0,1fr)]">
      <div>
        <h2 id="ats-title" className="kicker text-ink-muted">
          ATS score
        </h2>
        <p className="num mt-1 text-[44px] leading-none font-medium tracking-tight text-ink" data-testid="ats-score">
          <span className="text-ink-muted">{fmt(cur?.score)}</span>
          <span className="mx-2 text-ink-faint" aria-hidden>
            →
          </span>
          <span className="sr-only"> to </span>
          {fmt(tl?.score)}
        </p>
        <p className="mt-2 text-[12px] text-ink-muted">
          Current → tailored, via Resume-Matcher scoring
          {ats?.keywords_source === "resume_matcher" ? " (its job keywords)" : ats?.keywords_source === "seekhunter" ? " (SeekHunter's job keywords)" : ""}
        </p>
        <ResumeMatcherStatusLine tid={tid} rm={rm} />
      </div>
      <ul className="space-y-3" aria-label="ATS breakdown">
        {PARTS.map(([k, label, w]) => (
          <PartBar key={k} label={label} weight={w} before={cur?.breakdown[k] ?? null} after={tl?.breakdown[k] ?? null} />
        ))}
      </ul>
      <div>
        <p className="kicker text-ink-muted">Missing keywords</p>
        {tl?.missing_keywords.length ? <Chips items={tl.missing_keywords} /> : <p className="mt-2 text-[13px] text-ink-muted">None</p>}
        {rm?.status === "done" && rm.recommendations.length > 0 && (
          <ul className="mt-4 list-disc space-y-1 pl-4 text-[12.5px] leading-relaxed text-ink-muted">
            {rm.recommendations.slice(0, 3).map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function Question({ q, n }: { q: InterviewQuestion; n: number }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="border-b border-rule">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-baseline gap-3 py-3 text-left hover:text-blue"
      >
        <span className="num w-6 shrink-0 text-[11.5px] text-ink-muted">{String(n).padStart(2, "0")}</span>
        <span className="min-w-0 flex-1 text-[15px] leading-snug">{q.question}</span>
        <span className="font-mono text-[12px] text-ink-muted" aria-hidden>
          {open ? "−" : "+"}
        </span>
      </button>
      {open && (
        <div className="pb-4 pl-9">
          {q.focus_area && <p className="kicker text-[10px] text-ink-muted">{q.focus_area}</p>}
          <ul className="mt-1.5 list-disc space-y-1 pl-4 text-[14px] leading-relaxed text-ink">
            {q.suggested_answer_points.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </div>
      )}
    </li>
  );
}

export function InterviewPrepSection({ prep }: { prep: InterviewPrep }) {
  const questions = [...(prep.resume_questions ?? []), ...(prep.project_follow_ups ?? [])];
  return (
    <section aria-labelledby="interview-prep-title" className="mt-14">
      <div className="flex items-baseline gap-x-6 border-b-2 border-ink pb-2">
        <h2 id="interview-prep-title" className="kicker text-ink">
          Interview prep
        </h2>
        <span className="num text-[11.5px] text-ink-muted">{questions.length} questions · via Resume-Matcher</span>
      </div>
      <div className="mt-4 grid gap-x-12 gap-y-10 min-[1100px]:grid-cols-2">
        <ol>
          {questions.map((q, i) => (
            <Question key={q.question} q={q} n={i + 1} />
          ))}
        </ol>
        <aside className="max-w-[75ch] space-y-7 text-[14px] leading-relaxed min-[1100px]:pt-3">
          {!!prep.role_fit_analysis?.length && (
            <div>
              <p className="kicker text-ink-muted">Role fit</p>
              <ul className="mt-1.5 list-disc space-y-1 pl-4">
                {prep.role_fit_analysis.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
            </div>
          )}
          {!!prep.skill_gaps?.length && (
            <div>
              <p className="kicker text-ink-muted">Skill gaps to prepare</p>
              <ul className="mt-2 divide-y divide-rule border-y border-rule">
                {prep.skill_gaps.map((g) => (
                  <li key={g.skill} className="py-2.5">
                    <p className="text-[14px] font-semibold text-ink">{g.skill}</p>
                    <p className="mt-0.5 text-ink-muted">{g.preparation_suggestion}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {!!prep.talking_points?.length && (
            <div>
              <p className="kicker text-ink-muted">Talking points</p>
              <ul className="mt-1.5 list-disc space-y-1 pl-4">
                {prep.talking_points.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}

export function OutreachSection({ message, recruiter }: { message: string; recruiter: string | null }) {
  return (
    <section aria-labelledby="outreach-title" className="mt-14">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b-2 border-ink pb-2">
        <h2 id="outreach-title" className="kicker text-ink">
          Outreach message
        </h2>
        <span className="num text-[11.5px] text-ink-muted">{message.length} chars</span>
        <CopyButton text={message} label="Copy outreach message" className="ml-auto lg:h-7" />
      </div>
      <p className={cn("mt-5 max-w-[68ch] text-[16px] leading-[1.65] whitespace-pre-line")}>{message}</p>
      {recruiter && (
        <p className="mt-3 text-[12.5px] text-ink-muted">Paste into a LinkedIn invite to {recruiter}.</p>
      )}
    </section>
  );
}
