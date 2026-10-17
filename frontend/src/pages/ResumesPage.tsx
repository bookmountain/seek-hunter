import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ResetFilters } from "@/components/ResetFilters";
import { Input } from "@/components/ui/input";
import { usePersistedFilters } from "@/hooks/usePersistedFilters";
import { api, errMsg } from "@/lib/api";
import { ago, cityName } from "@/lib/format";
import type { TailoringListItem, TailoringStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_FILTERS: ["" | TailoringStatus, string][] = [
  ["", "All"],
  ["done", "Done"],
  ["running", "Running"],
  ["failed", "Failed"],
];

const isActive = (s: TailoringStatus) => s === "running" || s === "queued";

const linkBtn =
  "inline-flex h-8 items-center border px-2.5 font-mono text-[10.5px] font-medium tracking-[0.1em] uppercase transition-colors";

function Thumb({ src, alt }: { src: string | null; alt: string }) {
  return (
    <div className="aspect-[1/1.414] w-full overflow-hidden border border-ink/80 bg-white">
      {src ? (
        <img src={src} alt={alt} loading="lazy" className="block w-full" />
      ) : (
        <div className="flex h-full items-center justify-center bg-hover">
          <span className="kicker text-[10px] text-ink-muted">No preview</span>
        </div>
      )}
    </div>
  );
}

function Card({ t }: { t: TailoringListItem }) {
  const view = `/jobs/${t.job_id}/tailor?run=${t.id}`;
  return (
    <li className="grid grid-cols-[96px_minmax(0,1fr)] gap-4 border-b border-rule py-4 sm:grid-cols-[120px_minmax(0,1fr)]">
      <Link to={view} aria-label={`View tailored resume for ${t.job_title}`} className="block hover:opacity-80">
        <Thumb src={t.thumbnail} alt={`Page 1 of the resume tailored for ${t.job_title}`} />
      </Link>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="num text-[11.5px] text-ink-muted" title={t.created_at}>
            #{t.id} · {ago(t.created_at)}
          </span>
          {t.status === "done" ? (
            <span className="kicker text-[10px] text-ink">Done</span>
          ) : isActive(t.status) ? (
            <span className="kicker text-[10px] text-blue">
              {t.status === "queued" ? "Queued" : t.progress || "Running"}…
            </span>
          ) : (
            <span className="kicker text-[10px] text-ink-muted">Failed</span>
          )}
          {t.applied_application_id && (
            <Link to="/history?tab=applications" className="kicker border border-blue px-1.5 py-[2px] text-[10px] text-blue hover:bg-selected">
              Applied with this
            </Link>
          )}
        </div>
        <Link to={view} className="mt-1 block text-[15px] leading-snug font-semibold text-ink hover:text-blue">
          {t.job_title}
        </Link>
        <p className="mt-0.5 text-[13px] text-ink-muted">
          {t.company || "—"}
          {t.city && (
            <>
              <span className="text-ink-faint"> · </span>
              {cityName(t.city)}
            </>
          )}
        </p>
        {t.status === "failed" && t.error && (
          <p className="mt-2 line-clamp-2 bg-chip px-2 py-1 font-mono text-[11.5px] text-ink-muted">{t.error}</p>
        )}
        <div className="mt-3 flex flex-wrap gap-1.5">
          <Link to={view} className={cn(linkBtn, "border-ink bg-ink text-white hover:border-blue hover:bg-blue")}>
            View
          </Link>
          {t.resume_pdf && (
            <a href={t.resume_pdf} download className={cn(linkBtn, "border-ink text-ink hover:border-blue hover:text-blue")}>
              Resume PDF
            </a>
          )}
          {t.cover_letter_pdf && (
            <a href={t.cover_letter_pdf} download className={cn(linkBtn, "border-ink text-ink hover:border-blue hover:text-blue")}>
              Cover letter PDF
            </a>
          )}
        </div>
      </div>
    </li>
  );
}

const FILTER_DEFAULTS = { q: "", status: "" };

export function ResumesPage() {
  const filters = usePersistedFilters("resumes", FILTER_DEFAULTS);
  const debounced = filters.values.q;
  const status = filters.values.status as "" | TailoringStatus;
  const setFilter = filters.set;
  const setStatus = (s: string) => setFilter({ status: s });
  const [q, setQ] = useState(debounced);
  useEffect(() => {
    if (q.trim() === debounced) return;
    const t = setTimeout(() => setFilter({ q: q.trim() }), 250);
    return () => clearTimeout(t);
  }, [q, debounced, setFilter]);
  const lastUrlQ = useRef(debounced);
  useEffect(() => {
    if (debounced !== lastUrlQ.current) {
      lastUrlQ.current = debounced;
      setQ(debounced);
    }
  }, [debounced]);

  const current = useQuery({
    queryKey: ["resume-current"],
    queryFn: api.resumeCurrent,
    refetchInterval: (query) => (query.state.data && !query.state.data.ready && !query.state.data.error ? 3000 : false),
  });
  const list = useQuery({
    queryKey: ["all-tailorings", debounced],
    queryFn: () => api.allTailorings(debounced || undefined),
    placeholderData: (p) => p,
    refetchInterval: (query) => (query.state.data?.some((t) => isActive(t.status)) ? 3000 : false),
  });
  const rows = (list.data ?? []).filter((t) => !status || (status === "running" ? isActive(t.status) : t.status === status));
  const cur = current.data;

  return (
    <div className="mx-auto w-full max-w-7xl px-5 py-8 lg:px-8 lg:py-10">
      <header className="border-b-2 border-ink pb-5">
        <p className="kicker text-ink-muted">Library</p>
        <h1 className="display mt-2 text-[44px] leading-none">Resumes</h1>
      </header>

      <div className="mt-8 grid gap-10 lg:grid-cols-[220px_minmax(0,1fr)]">
        <section aria-labelledby="current-resume">
          <h2 id="current-resume" className="kicker border-b border-ink pb-2 text-ink">
            Current resume
          </h2>
          <div className="mt-4 max-w-[220px]">
            <Thumb src={cur?.ready ? (cur.page_urls[0] ?? null) : null} alt="Page 1 of your current resume" />
            <p className="num mt-2 text-[11.5px] text-ink-muted">
              {cur?.ready ? `${cur.pages} ${cur.pages === 1 ? "page" : "pages"}` : cur?.error ? cur.error : "Building preview…"}
            </p>
            {cur?.pdf_url && (
              <a href={cur.pdf_url} download className={cn(linkBtn, "mt-3 border-ink text-ink hover:border-blue hover:text-blue")}>
                Download PDF
              </a>
            )}
          </div>
        </section>

        <section aria-labelledby="tailored-list" className="min-w-0">
          <div className="flex flex-wrap items-end justify-between gap-3 border-b border-ink pb-2">
            <h2 id="tailored-list" className="kicker text-ink">
              Tailored <span className="num text-ink-muted">{list.data ? `· ${rows.length}` : ""}</span>
            </h2>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Input className="w-full sm:w-72" placeholder="Search job title or company" aria-label="Search tailored resumes" value={q} onChange={(e) => setQ(e.target.value)} />
            <div role="group" aria-label="Filter by status" className="inline-flex border border-ink">
              {STATUS_FILTERS.map(([v, label], i) => (
                <button
                  key={v || "all"}
                  type="button"
                  aria-pressed={status === v}
                  onClick={() => setStatus(v)}
                  className={cn(
                    "h-8 px-3 font-mono text-[10.5px] font-medium tracking-[0.1em] uppercase",
                    i > 0 && "border-l border-ink",
                    status === v ? "bg-ink text-white" : "text-ink hover:text-blue",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
            <ResetFilters onReset={() => { setQ(""); filters.reset(); }} disabled={filters.isDefault && !q} />
          </div>
          {list.error ? (
            <p className="mt-6 bg-chip px-4 py-3 text-sm">{errMsg(list.error)}</p>
          ) : (
            <ul className="mt-2 grid gap-x-10 xl:grid-cols-2">
              {rows.map((t) => (
                <Card key={t.id} t={t} />
              ))}
            </ul>
          )}
          {list.data && !list.data.length && !debounced && (
            <p className="py-14 text-center text-[15px] text-ink-muted">No tailored resumes yet. Open a job and press Tailor resume.</p>
          )}
          {list.data && (list.data.length > 0 || debounced) && !rows.length && (
            <p className="py-10 text-center text-sm text-ink-muted">Nothing matches.</p>
          )}
        </section>
      </div>
    </div>
  );
}
