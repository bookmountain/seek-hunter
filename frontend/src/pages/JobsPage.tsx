import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { DetailEmpty, JobDetail } from "@/components/JobDetail";
import { JobList, type JobSort } from "@/components/JobList";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ResetFilters } from "@/components/ResetFilters";
import { DESKTOP_QUERY, useMediaQuery } from "@/hooks/useMediaQuery";
import { usePersistedFilters } from "@/hooks/usePersistedFilters";
import { api, errMsg } from "@/lib/api";
import { cityName } from "@/lib/format";
import type { Job } from "@/lib/types";
import { cn, parseIsoUtc } from "@/lib/utils";

const ALL = "all";

/** Remembered per page ("jobs" / "excluded"); `job` (the open ad) is deliberately not persisted. */
const FILTER_DEFAULTS = { q: "", city: "", work_type: "", status: "", source: "", sort: "score" };

const time = (iso: string | null) => (iso ? parseIsoUtc(iso).getTime() : -Infinity);

/** Client-side order over the loaded page (the API returns up to 500 rows). Newest first for dates. */
function sortJobs(jobs: Job[], sort: JobSort): Job[] {
  const rows = [...jobs];
  if (sort === "listed") rows.sort((a, b) => time(b.listed_at) - time(a.listed_at) || b.final_score - a.final_score);
  else if (sort === "seen") rows.sort((a, b) => time(b.first_seen_at) - time(a.first_seen_at) || b.final_score - a.final_score);
  else rows.sort((a, b) => b.final_score - a.final_score || time(b.listed_at) - time(a.listed_at));
  return rows;
}

const isTypingTarget = (el: EventTarget | null) =>
  el instanceof HTMLElement &&
  (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || !!el.closest('[role="listbox"],[role="dialog"]'));

export function JobsPage({ view }: { view: "active" | "excluded" }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = usePersistedFilters(view === "excluded" ? "excluded" : "jobs", FILTER_DEFAULTS);
  const { q: urlQ, city, work_type: workType, status, source } = filters.values;
  const setFilter = filters.set;
  const [q, setQ] = useState(urlQ);
  const navigate = useNavigate();
  const isDesktop = useMediaQuery(DESKTOP_QUERY);
  const selectedId = Number(searchParams.get("job")) || null;
  // True when the open detail was pushed onto history from the list, so "Back" can pop it.
  const pushedRef = useRef(false);
  const listScrollRef = useRef(0);
  const detailPaneRef = useRef<HTMLDivElement>(null);

  // Typing updates the URL (and so the query) after a short pause; external changes
  // (saved prefs applied, reset) flow back into the box.
  useEffect(() => {
    if (q === urlQ) return;
    const t = setTimeout(() => setFilter({ q }), 250);
    return () => clearTimeout(t);
  }, [q, urlQ, setFilter]);
  const lastUrlQ = useRef(urlQ);
  useEffect(() => {
    if (urlQ !== lastUrlQ.current) {
      lastUrlQ.current = urlQ;
      setQ(urlQ);
    }
  }, [urlQ]);

  const params = {
    view,
    q: urlQ,
    work_type: workType || undefined,
    status: status || undefined,
    source: source || undefined,
    city: city || undefined,
    limit: "500",
  };
  const { data: cities = [] } = useQuery({ queryKey: ["job-cities", view], queryFn: () => api.jobCities(view) });
  const cityOptions: [string, string][] = [
    [ALL, "All locations"],
    ...cities.map((c): [string, string] => [c.city, `${cityName(c.city)} ${c.count}`]),
    ...(city && !cities.some((c) => c.city === city) ? [[city, cityName(city)] as [string, string]] : []),
  ];
  const pick = (key: keyof typeof FILTER_DEFAULTS) => (v: string) => setFilter({ [key]: v === ALL ? "" : v });
  const { data: rawJobs = [], isLoading: loadingJobs, error } = useQuery({
    queryKey: ["jobs", params],
    queryFn: () => api.jobs(params),
    enabled: filters.ready,
  });
  const isLoading = loadingJobs || !filters.ready;
  const sort = (["score", "listed", "seen"].includes(filters.values.sort) ? filters.values.sort : "score") as JobSort;
  const data = useMemo(() => sortJobs(rawJobs, sort), [rawJobs, sort]);

  const setJob = useCallback(
    (id: number | null, replace: boolean) =>
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (id === null) next.delete("job");
          else next.set("job", String(id));
          return next;
        },
        { replace },
      ),
    [setSearchParams],
  );

  const open = (j: Job) => {
    if (j.id === selectedId) return;
    // Push a history entry only when opening from the bare list; switching between
    // jobs in the split view replaces it so Back doesn't walk through every row.
    const push = selectedId === null;
    if (!isDesktop) listScrollRef.current = window.scrollY;
    pushedRef.current = push;
    setJob(j.id, !push);
  };

  const close = useCallback(() => {
    if (pushedRef.current) {
      pushedRef.current = false;
      navigate(-1);
    } else {
      setJob(null, true);
    }
  }, [navigate, setJob]);

  // Esc clears the selection (unless typing, or a popup/dialog owns the key).
  useEffect(() => {
    if (selectedId === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented || isTypingTarget(e.target)) return;
      const row = document.querySelector<HTMLElement>(`[data-job-id="${selectedId}"]`);
      close();
      requestAnimationFrame(() => row?.focus());
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedId, close]);

  // Detail pane starts at the top for each job; on mobile the full-screen view does too,
  // and returning to the list restores where the reader was.
  useLayoutEffect(() => {
    detailPaneRef.current?.scrollTo?.({ top: 0 });
    if (isDesktop) return;
    window.scrollTo?.({ top: selectedId ? 0 : listScrollRef.current });
  }, [selectedId, isDesktop]);

  const selectedRow = data.find((j) => j.id === selectedId);

  const select = (value: string, onChange: (v: string) => void, options: [string, string][], label: string) => (
    <Select value={value} onValueChange={(v) => onChange(v as string)} items={Object.fromEntries(options)}>
      <SelectTrigger className="min-w-0 flex-1 basis-[calc(50%-0.25rem)] sm:w-[8.25rem] sm:flex-none sm:basis-auto" aria-label={label}>
        <SelectValue placeholder={label} />
      </SelectTrigger>
      <SelectContent>
        {options.map(([v, l]) => (
          <SelectItem key={v} value={v}>
            {l}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );

  return (
    <div className="lg:grid lg:h-full lg:grid-cols-[minmax(0,58fr)_minmax(0,42fr)]">
      {/* Left: the classifieds column */}
      <section
        aria-label={view === "excluded" ? "Excluded jobs" : "Jobs"}
        className={cn("min-w-0 lg:overflow-y-auto lg:border-r lg:border-ink", selectedId !== null && "hidden lg:block")}
      >
        <div className="paper sticky top-0 z-10 border-b border-ink px-5 py-3 lg:top-0 lg:px-6">
          <div className="flex items-baseline justify-between gap-4 pb-3">
            <h1 className="display text-[28px] leading-none">
              {view === "excluded" ? "Excluded" : "Jobs"}
            </h1>
            <span className="flex items-baseline gap-4">
              <ResetFilters onReset={() => { setQ(""); filters.reset(); }} disabled={filters.isDefault && !q} />
              <span className="num text-[12px] text-ink-muted" aria-live="polite">
                {isLoading ? "Loading…" : `${data.length} ${data.length === 1 ? "job" : "jobs"}`}
              </span>
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              className="w-full sm:w-52"
              placeholder="Search title or company"
              aria-label="Search title or company"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            {select(city || ALL, pick("city"), cityOptions, "Location")}
            {select(workType || ALL, pick("work_type"), [[ALL, "All types"], ["part_time", "Part time"], ["contract", "Contract"], ["casual", "Casual"], ["full_time", "Full time"]], "Work type")}
            {view === "active" &&
              select(status || ALL, pick("status"), [[ALL, "Any status"], ["new", "New"], ["saved", "Saved"], ["applied", "Applied"], ["hidden", "Hidden"], ["closed", "Closed"]], "Status")}
            {select(source || ALL, pick("source"), [[ALL, "All sources"], ["seek", "SEEK"], ["jora", "Jora"], ["linkedin", "LinkedIn"]], "Source")}
          </div>
        </div>
        {error ? (
          <p className="px-6 py-16 text-center text-ink">{errMsg(error)}</p>
        ) : isLoading ? (
          <p className="kicker px-6 py-16 text-center text-ink-muted">Loading…</p>
        ) : (
          <JobList
            jobs={data}
            view={view}
            selectedId={selectedId}
            onSelect={open}
            sort={sort}
            onSort={(s) => setFilter({ sort: s })}
            onArrowSelect={(j) => isDesktop && open(j)}
          />
        )}
      </section>

      {/* Right: the detail pane (desktop) / full-screen view (mobile) */}
      <section
        ref={detailPaneRef}
        aria-label="Job detail"
        className={cn("min-w-0 lg:block lg:overflow-y-auto", selectedId === null && "hidden")}
      >
        {selectedId !== null ? (
          <>
            <div className="paper sticky top-0 z-10 border-b border-ink px-5 py-2.5 sm:px-8 lg:hidden">
              <button type="button" onClick={close} className="kicker py-1 text-blue hover:underline">
                <span aria-hidden>←</span> Back to list
              </button>
            </div>
            <JobDetail key={selectedId} id={selectedId} row={selectedRow} onClose={close} />
          </>
        ) : (
          <DetailEmpty count={data.length} />
        )}
      </section>
    </div>
  );
}
