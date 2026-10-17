import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { DetailEmpty, JobDetail } from "@/components/JobDetail";
import { JobList } from "@/components/JobList";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DESKTOP_QUERY, useMediaQuery } from "@/hooks/useMediaQuery";
import { api, errMsg } from "@/lib/api";
import type { Job } from "@/lib/types";
import { cn } from "@/lib/utils";

const ALL = "all";

const isTypingTarget = (el: EventTarget | null) =>
  el instanceof HTMLElement &&
  (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || !!el.closest('[role="listbox"],[role="dialog"]'));

export function JobsPage({ view }: { view: "active" | "excluded" }) {
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [workType, setWorkType] = useState(ALL);
  const [status, setStatus] = useState(ALL);
  const [source, setSource] = useState(ALL);

  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const isDesktop = useMediaQuery(DESKTOP_QUERY);
  const selectedId = Number(searchParams.get("job")) || null;
  // True when the open detail was pushed onto history from the list, so "Back" can pop it.
  const pushedRef = useRef(false);
  const listScrollRef = useRef(0);
  const detailPaneRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q), 250);
    return () => clearTimeout(t);
  }, [q]);

  const params = {
    view,
    q: debouncedQ,
    work_type: workType === ALL ? undefined : workType,
    status: status === ALL ? undefined : status,
    source: source === ALL ? undefined : source,
  };
  const { data = [], isLoading, error } = useQuery({ queryKey: ["jobs", params], queryFn: () => api.jobs(params) });

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
      <SelectTrigger className="min-w-0 flex-1 basis-0 sm:w-36 sm:flex-none sm:basis-auto" aria-label={label}>
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
            <h1 className="display text-[26px] leading-none font-semibold tracking-[-0.01em]">
              {view === "excluded" ? "Excluded" : "Situations vacant"}
            </h1>
            <span className="num text-[12px] text-ink-muted" aria-live="polite">
              {isLoading ? "Loading…" : `${data.length} ${data.length === 1 ? "job" : "jobs"}`}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              className="w-full sm:w-60"
              placeholder="Search title or company"
              aria-label="Search title or company"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            {select(workType, setWorkType, [[ALL, "All types"], ["part_time", "Part time"], ["contract", "Contract"], ["casual", "Casual"], ["full_time", "Full time"]], "Work type")}
            {view === "active" &&
              select(status, setStatus, [[ALL, "Any status"], ["new", "New"], ["saved", "Saved"], ["applied", "Applied"], ["hidden", "Hidden"]], "Status")}
            {select(source, setSource, [[ALL, "All sources"], ["seek", "SEEK"], ["jora", "Jora"]], "Source")}
          </div>
        </div>
        {error ? (
          <p className="px-6 py-16 text-center text-signal">{errMsg(error)}</p>
        ) : isLoading ? (
          <p className="kicker px-6 py-16 text-center text-ink-muted">Setting type…</p>
        ) : (
          <JobList
            jobs={data}
            view={view}
            selectedId={selectedId}
            onSelect={open}
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
              <button type="button" onClick={close} className="kicker py-1 text-ink hover:text-signal">
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
