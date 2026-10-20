import { type KeyboardEvent, useEffect, useRef } from "react";
import { cityName, since, sourceName } from "@/lib/format";
import type { Job, JobStatus } from "@/lib/types";
import { cn, parseIsoUtc } from "@/lib/utils";
import { Score } from "./Score";
import { WorkTypeLabel } from "./WorkTypeLabel";

const STATUS_CLASS: Record<JobStatus, string> = {
  new: "text-ink-muted",
  saved: "text-ink",
  applied: "text-blue",
  hidden: "text-ink-muted line-through decoration-1",
};

const MAX_SKILLS = 3;

export type JobSort = "score" | "listed" | "seen";

const DAY_MS = 86_400_000;
const isFresh = (iso: string | null) => !!iso && Date.now() - parseIsoUtc(iso).getTime() <= DAY_MS;
const exactAdelaide = (iso: string) =>
  parseIsoUtc(iso).toLocaleString("en-AU", {
    timeZone: "Australia/Adelaide",
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });

function Listed({ iso, className }: { iso: string | null; className?: string }) {
  if (!iso) return <span className={cn("text-ink-faint", className)}>—</span>;
  return (
    <span title={`Listed ${exactAdelaide(iso)} (Adelaide)`} className={cn(isFresh(iso) ? "font-medium text-blue" : "text-ink-muted", className)}>
      {since(iso)}
    </span>
  );
}

/** Set once the first list has painted, so the reveal runs only on page load. */
let revealed = false;

function Skills({ skills }: { skills: string[] }) {
  if (!skills.length) return <span className="text-ink-faint">—</span>;
  const shown = skills.slice(0, MAX_SKILLS);
  const rest = skills.length - shown.length;
  return (
    <span className="font-mono text-[12px] leading-[1.6] text-ink-muted">
      {shown.join(", ")}
      {rest > 0 && <span className="text-ink-muted"> +{rest}</span>}
    </span>
  );
}

function Reasons({ reasons }: { reasons: string[] }) {
  return (
    <span className="flex flex-wrap gap-1">
      {reasons.map((r) => (
        <span key={r} className="kicker bg-chip px-1.5 py-[3px] leading-none text-ink">
          {r}
        </span>
      ))}
    </span>
  );
}

// Column template shared by the column head and rows. Narrow containers fold
// type/skills under the title; wide ones (>= 48rem) get a true classifieds grid.
const GRID =
  "grid grid-cols-[3.25rem_minmax(0,1fr)_auto] gap-x-4 @4xl:grid-cols-[3.25rem_minmax(0,1fr)_4.5rem_6.25rem_8rem_3.5rem_2.5rem_4.25rem] @4xl:gap-x-3";

const SORT_LABEL: Record<JobSort, string> = { score: "Score", listed: "Listed", seen: "Seen" };

function SortHead({ sort, current, onSort, className }: { sort: JobSort; current: JobSort; onSort: (s: JobSort) => void; className?: string }) {
  const active = sort === current;
  return (
    <button
      type="button"
      onClick={() => onSort(sort)}
      aria-pressed={active}
      aria-label={`Sort by ${SORT_LABEL[sort].toLowerCase()}`}
      className={cn("kicker text-[10px] whitespace-nowrap hover:text-blue", active ? "text-ink underline decoration-blue decoration-2 underline-offset-4" : "text-ink-muted", className)}
    >
      {SORT_LABEL[sort]}
      {active && <span aria-hidden> ↓</span>}
    </button>
  );
}

export function JobList({
  jobs,
  view,
  selectedId,
  onSelect,
  onArrowSelect,
  sort = "score",
  onSort = () => {},
}: {
  sort?: JobSort;
  onSort?: (s: JobSort) => void;
  jobs: Job[];
  view: "active" | "excluded";
  selectedId: number | null;
  onSelect: (j: Job) => void;
  /** Called when the keyboard moves the cursor to a row (desktop selects immediately). */
  onArrowSelect: (j: Job) => void;
}) {
  const listRef = useRef<HTMLOListElement>(null);
  // Stagger the reveal only for the rows present on the first page load.
  const animate = !revealed;
  useEffect(() => {
    if (jobs.length) revealed = true;
  }, [jobs.length]);

  const onKeyDown = (e: KeyboardEvent<HTMLOListElement>) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const rows = Array.from(listRef.current?.querySelectorAll<HTMLButtonElement>("[data-row]") ?? []);
    if (!rows.length) return;
    e.preventDefault();
    const focused = rows.indexOf(document.activeElement as HTMLButtonElement);
    const selected = jobs.findIndex((j) => j.id === selectedId);
    const from = focused >= 0 ? focused : selected;
    const next =
      from < 0 ? 0 : Math.min(rows.length - 1, Math.max(0, from + (e.key === "ArrowDown" ? 1 : -1)));
    rows[next].focus();
    onArrowSelect(jobs[next]);
  };

  if (!jobs.length) {
    return (
      <div className="px-6 py-20 text-center">
        <p className="display text-2xl text-ink">No matches.</p>
        <p className="mt-2 text-sm text-ink-muted">No jobs match these filters yet.</p>
      </div>
    );
  }

  return (
    <div className="@container">
      <div role="group" aria-label="Sort jobs" className={cn(GRID, "kicker hidden border-b-2 border-ink px-5 py-2 text-[10px] text-ink-muted @4xl:grid lg:px-6")}>
        <span>
          <SortHead sort="score" current={sort} onSort={onSort} />
        </span>
        <span>Position</span>
        <span>Source</span>
        <span>Type</span>
        <span>{view === "excluded" ? "Reason" : "Skills"}</span>
        <span className="text-right">
          <SortHead sort="listed" current={sort} onSort={onSort} />
        </span>
        <span className="text-right">
          <SortHead sort="seen" current={sort} onSort={onSort} />
        </span>
        <span className="text-right">Status</span>
      </div>
      {/* narrow layout: the column heads are hidden, so offer the sort as a compact row */}
      <div role="group" aria-label="Sort jobs (compact)" className="flex items-center gap-4 border-b border-rule px-5 py-2 @4xl:hidden lg:px-6">
        <span className="kicker text-[10px] text-ink-faint">Sort</span>
        {(["score", "listed", "seen"] as const).map((k) => (
          <SortHead key={k} sort={k} current={sort} onSort={onSort} />
        ))}
      </div>
      <ol ref={listRef} onKeyDown={onKeyDown} aria-label="Jobs">
        {jobs.map((j, i) => {
          const selected = j.id === selectedId;
          const hours = j.flags.includes("hours");
          const policeCheck = j.flags.includes("police_check");
          const firstSnippet = view === "excluded" ? Object.values(j.snippets)[0] : undefined;
          return (
            <li
              key={j.id}
              className={cn("border-b border-rule", animate && "reveal")}
              style={animate ? ({ "--i": i } as React.CSSProperties) : undefined}
            >
              <button
                type="button"
                data-row
                data-job-id={j.id}
                aria-current={selected ? "true" : undefined}
                onClick={() => onSelect(j)}
                className={cn(
                  GRID,
                  "relative w-full px-5 py-4 text-left transition-colors outline-none lg:px-6",
                  "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-blue",
                  "before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:bg-blue before:opacity-0 before:transition-opacity",
                  selected ? "bg-selected before:opacity-100" : "hover:bg-hover",
                )}
              >
                <span className="pt-0.5">
                  <Score score={j.final_score} className="text-[28px]" />
                </span>

                <span className="min-w-0">
                  <span className="block text-[15px] leading-snug font-semibold text-pretty text-ink">{j.title}</span>
                  <span className="mt-1 block text-[13px] leading-snug text-ink-muted">
                    {j.company}
                    <span className="text-ink-faint"> · </span>
                    <span className="whitespace-nowrap">{j.location}</span>
                    <span className="whitespace-nowrap">
                      <span className="@4xl:hidden">
                        <span className="text-ink-faint"> · </span>
                        <span className="font-mono text-[11px] tracking-[0.06em] uppercase">{sourceName(j.source)}</span>
                        <span className="text-ink-faint"> · </span>
                        <span className="font-mono text-[11.5px]">
                          listed <Listed iso={j.listed_at} />
                        </span>
                      </span>
                      {j.city && j.city !== "adelaide" && (
                        <span className="ml-2 font-mono text-[10.5px] tracking-[0.1em] text-ink uppercase">{cityName(j.city)}</span>
                      )}
                      {j.contact_phone && (
                        <span
                          title={`Recruiter phone: ${j.contact_phone}`}
                          className="ml-2 border border-rule px-1 py-px align-[1px] font-mono text-[9.5px] font-medium tracking-[0.1em] text-ink-muted"
                        >
                          TEL
                        </span>
                      )}
                      {j.applicant_count !== null && (
                        <span
                          title={`${j.applicant_count} applicants on SEEK`}
                          className="ml-2 border border-rule px-1 py-px align-[1px] font-mono text-[9.5px] font-medium tracking-[0.1em] text-ink-muted"
                        >
                          {j.applicant_count} APPS
                        </span>
                      )}
                      {j.application ? (
                        <span
                          title={`Applied · ${j.application.stage.replace("_", " ")}`}
                          className="ml-2 border border-blue px-1 py-px align-[1px] font-mono text-[9.5px] font-medium tracking-[0.1em] text-blue"
                        >
                          APPLIED
                        </span>
                      ) : j.prior_applications?.length ? (
                        <span
                          title={`${j.company} already has your resume (${j.prior_applications.length})`}
                          className="ml-2 bg-chip px-1 py-px align-[1px] font-mono text-[9.5px] font-medium tracking-[0.1em] text-ink"
                        >
                          HAS RESUME
                        </span>
                      ) : null}
                    </span>
                  </span>
                  {firstSnippet && (
                    <span className="mt-1 block truncate font-mono text-[11.5px] text-ink-muted">…{firstSnippet}…</span>
                  )}
                  {/* folded layout (narrow column) */}
                  <span className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1 @4xl:hidden">
                    <WorkTypeLabel type={j.work_type} hours={hours} policeCheck={policeCheck} />
                    {view === "excluded" ? <Reasons reasons={j.reasons} /> : <Skills skills={j.matched_skills} />}
                  </span>
                </span>

                <span className="hidden pt-1 @4xl:block">
                  <span data-col="source" className="font-mono text-[11px] font-medium tracking-[0.1em] text-ink uppercase">
                    {sourceName(j.source)}
                  </span>
                </span>
                <span className="hidden pt-1 @4xl:block">
                  <WorkTypeLabel type={j.work_type} hours={hours} policeCheck={policeCheck} className="flex-col items-start" />
                </span>
                <span className="hidden pt-0.5 @4xl:block">
                  {view === "excluded" ? <Reasons reasons={j.reasons} /> : <Skills skills={j.matched_skills} />}
                </span>
                <span data-col="listed" className="num hidden pt-0.5 text-right text-[12px] @4xl:block">
                  <Listed iso={j.listed_at} />
                </span>
                <span className="num hidden pt-0.5 text-right text-[12px] text-ink-muted @4xl:block">
                  {since(j.first_seen_at)}
                </span>
                <span className="flex flex-col items-end gap-1 pt-0.5 text-right">
                  <span className="num text-[12px] text-ink-muted @4xl:hidden">{since(j.first_seen_at)}</span>
                  <span className={cn("kicker text-[10.5px]", STATUS_CLASS[j.status])}>{j.status}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
