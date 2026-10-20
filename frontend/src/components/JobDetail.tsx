import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import DOMPurify from "dompurify";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api, errMsg } from "@/lib/api";
import { cityName, since, sourceName } from "@/lib/format";
import type { Job, JobStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CompetitionBlock } from "./CompetitionBlock";
import { ApplicationRow, PriorApplicationsBox } from "./history/JobHistoryBits";
import { RecruiterBlock } from "./RecruiterBlock";
import { Score } from "./Score";
import { TailorAction } from "./TailorAction";
import { WorkTypeLabel } from "./WorkTypeLabel";

export function highlight(html: string, skills: string[]): string {
  const clean = DOMPurify.sanitize(html);
  if (!skills.length) return clean;
  const escaped = skills.map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const re = new RegExp(`(?<![\\w#+.])(${escaped.join("|")})(?![\\w#+])`, "gi");
  return clean.replace(/>([^<]+)</g, (_m, text: string) => `>${text.replace(re, "<mark>$1</mark>")}<`);
}

const STATUSES: { value: JobStatus; label: string }[] = [
  { value: "saved", label: "Saved" },
  { value: "applied", label: "Applied" },
  { value: "hidden", label: "Hidden" },
  { value: "new", label: "New" },
];

/** Typographic placeholder for the right-hand pane when nothing is selected. */
export function DetailEmpty({ count }: { count: number }) {
  return (
    <div className="flex h-full min-h-[60vh] items-center justify-center px-10">
      <div className="max-w-sm text-center">
        <div aria-hidden className="mx-auto mb-6 size-3 bg-blue" />
        <p className="display text-[28px] leading-tight text-ink">Select a job.</p>
        <p className="mt-4 text-sm text-ink-muted">
          {count} listed. The full ad, its score and your notes open here.
        </p>
        <p className="kicker mt-6 text-ink-muted">
          <kbd className="font-mono">↑</kbd> <kbd className="font-mono">↓</kbd> to browse · <kbd className="font-mono">Esc</kbd> to clear
        </p>
      </div>
    </div>
  );
}

export function JobDetail({ id, row, onClose }: { id: number; row?: Job; onClose: () => void }) {
  const qc = useQueryClient();
  const { data, error } = useQuery({ queryKey: ["job", id], queryFn: () => api.job(id) });
  // `data` (the fetched detail) wins once loaded so status/notes reflect the latest PATCH;
  // `row` (from the list) is only the fallback shown before the fetch resolves.
  const view: Job | undefined = data ?? row;
  const [notes, setNotes] = useState(view?.notes ?? "");
  useEffect(() => setNotes(view?.notes ?? ""), [view?.notes]);

  const done = (msg: string) => {
    toast.success(msg);
    qc.invalidateQueries({ queryKey: ["jobs"] });
    qc.invalidateQueries({ queryKey: ["job", id] });
    for (const key of ["applications", "contacts", "companies", "history"]) qc.invalidateQueries({ queryKey: [key] });
  };
  const fail = (e: Error) => toast.error(errMsg(e));
  const patch = useMutation({
    mutationFn: (body: { status?: JobStatus; notes?: string }) => api.patchJob(id, body),
    onSuccess: () => done("Saved"),
    onError: fail,
  });
  const unexclude = useMutation({
    mutationFn: (allow: boolean) => api.unexclude(id, allow),
    onSuccess: (_result, allow) => {
      done("Moved to jobs");
      if (allow) qc.invalidateQueries({ queryKey: ["settings"] });
      onClose();
    },
    onError: fail,
  });

  if (!view) {
    return (
      <div className="px-6 py-10 lg:px-10">
        <p className="kicker text-ink-muted">{error ? errMsg(error) : "Loading advertisement…"}</p>
      </div>
    );
  }

  const body = data?.description_html || data?.teaser || "";

  return (
    <article className="px-5 pt-6 pb-16 sm:px-8 lg:px-10 lg:pt-8" aria-labelledby="job-title">
      <div className="max-w-[68ch]">
        <p className="kicker flex flex-wrap gap-x-3 gap-y-1 text-ink-muted">
          <span>{sourceName(view.source)}</span>
          {view.city && (
            <>
              <span aria-hidden>/</span>
              <span className={view.city === "adelaide" ? undefined : "text-ink"}>{cityName(view.city)}</span>
            </>
          )}
          <span aria-hidden>/</span>
          <span>No. {view.id}</span>
          <span aria-hidden>/</span>
          <span>Seen {since(view.first_seen_at)} ago</span>
          {view.listed_at && (
            <>
              <span aria-hidden>/</span>
              <span>Listed {since(view.listed_at)} ago</span>
            </>
          )}
        </p>

        <h1
          id="job-title"
          className="display mt-3 text-[30px] leading-[1.04] text-balance sm:text-[38px]"
        >
          {view.title}
        </h1>

        <p className="mt-3 text-[15px] leading-snug">
          <span className="font-semibold">{view.company}</span>
          <span className="text-ink-faint"> · </span>
          <span className="text-ink-muted">{view.location}</span>
          {view.salary_label && (
            <>
              <span className="text-ink-faint"> · </span>
              <span className="num text-[13.5px] whitespace-nowrap text-ink">{view.salary_label}</span>
            </>
          )}
        </p>

        {view.prior_applications?.length > 0 && <PriorApplicationsBox company={view.company} prior={view.prior_applications} />}

        {/* Score ledger */}
        <div className="mt-6 grid grid-cols-[auto_1fr] items-end gap-x-6 border-y-2 border-ink py-4">
          <Score score={view.final_score} className="text-[56px]" />
          <dl className="num grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 pb-1 text-[12.5px]">
            <dt className="kicker self-center text-ink-muted">Rules</dt>
            <dd>{view.rule_score}</dd>
            <dt className="kicker self-center text-ink-muted">AI</dt>
            <dd>{view.llm_score ?? <span className="text-ink-muted">not scored</span>}</dd>
            <dt className="kicker self-center text-ink-muted">Type</dt>
            <dd>
              <WorkTypeLabel type={view.work_type} hours={view.flags.includes("hours")} policeCheck={view.flags.includes("police_check")}
                bank={view.flags.includes("bank")}
              />
            </dd>
          </dl>
        </div>

        {view.llm_note && (
          <blockquote className="mt-6 border-l-2 border-blue pl-4">
            <p className="kicker text-blue">AI</p>
            <p className="mt-1.5 text-[16px] leading-relaxed text-ink">{view.llm_note}</p>
          </blockquote>
        )}

        {view.excluded && (
          <section className="mt-6 border border-ink p-4" aria-label="Exclusion">
            <p className="kicker text-ink">Excluded</p>
            <ul className="mt-2 space-y-2 text-sm">
              {view.reasons.map((reason) => (
                <li key={reason}>
                  <span className="kicker mr-2 bg-chip px-1.5 py-[3px] text-ink">{reason}</span>
                  {view.snippets[reason] && <span className="text-ink-muted">…{view.snippets[reason]}…</span>}
                </li>
              ))}
            </ul>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => unexclude.mutate(false)}>
                Un-exclude
              </Button>
              <Button size="sm" variant="outline" onClick={() => unexclude.mutate(true)}>
                Un-exclude + allowlist {view.company}
              </Button>
            </div>
          </section>
        )}

        {view.matched_skills.length > 0 && (
          <div className="mt-6">
            <p className="kicker text-ink-muted">Matched skills</p>
            <p className="mt-1.5 font-mono text-[13px] leading-relaxed">
              {view.matched_skills.join(", ")}
            </p>
          </div>
        )}

        <CompetitionBlock job={view} />

        <RecruiterBlock job={view} jobId={view.id} />

        {/* Actions */}
        <div className="mt-7 flex flex-wrap items-center gap-3">
          <TailorAction jobId={view.id}>
            <Button variant="outline" render={<a href={view.url} target="_blank" rel="noreferrer" />}>
              Open on {sourceName(view.source)} <span aria-hidden>↗</span>
            </Button>
          </TailorAction>
          <div role="group" aria-label="Status" className="inline-flex border border-ink">
            {STATUSES.map((s, i) => {
              const active = view.status === s.value;
              return (
                <button
                  key={s.value}
                  type="button"
                  aria-pressed={active}
                  onClick={() => patch.mutate({ status: s.value })}
                  className={cn(
                    "h-9 px-3 font-mono text-[11px] font-medium tracking-[0.1em] uppercase transition-colors",
                    i > 0 && "border-l border-ink",
                    active ? "bg-ink text-white" : "text-ink hover:bg-hover hover:text-blue",
                  )}
                >
                  {s.label}
                </button>
              );
            })}
          </div>
        </div>

        {view.application && <ApplicationRow jobId={view.id} app={view.application} />}

        <div className="mt-6">
          <label htmlFor={`notes-${view.id}`} className="kicker text-ink-muted">
            Notes
          </label>
          <Textarea
            id={`notes-${view.id}`}
            className="mt-1.5"
            placeholder="Who to contact, what to mention, follow-up date…"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          <Button size="sm" variant="outline" className="mt-2" onClick={() => patch.mutate({ notes })}>
            Save notes
          </Button>
        </div>

        {/* Section divider: the ad itself */}
        <div className="mt-10 mb-6 flex items-center gap-4" aria-hidden>
          <span className="kicker text-ink">Advertisement</span>
          <span className="h-0.5 flex-1 bg-ink" />
        </div>

        {body ? (
          <div className="article" dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(highlight(body, view.matched_skills)) }} />
        ) : (
          <p className="text-sm text-ink-muted">{data ? "No description captured." : "Loading description…"}</p>
        )}
      </div>
    </article>
  );
}
