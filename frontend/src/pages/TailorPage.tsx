import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ChangesPanel } from "@/components/tailor/ChangesPanel";
import { CoverLetterSection } from "@/components/tailor/CoverLetterSection";
import { PagePreviews } from "@/components/tailor/PagePreviews";
import { AtsBlock, InterviewPrepSection, OutreachSection } from "@/components/tailor/ResumeMatcher";
import { Button } from "@/components/ui/button";
import { api, errMsg } from "@/lib/api";
import { adelaideTime, WORK_TYPE_CAPS } from "@/lib/format";
import type { TailoringDetail, TailoringStatus, TailoringSummary } from "@/lib/types";
import { cn, parseIsoUtc } from "@/lib/utils";

const isActive = (s?: TailoringStatus) => s === "queued" || s === "running";
const rmBusy = (t?: TailoringDetail) => t?.resume_matcher?.status === "queued" || t?.resume_matcher?.status === "running";
const letterBusy = (t?: TailoringDetail) => t?.cover_letter_regen?.status === "queued" || t?.cover_letter_regen?.status === "running";

const STEPS = ["Reading resume", "Rendering current resume", "Tailoring with AI", "Compiling PDFs"];

function elapsed(from: string, now: number) {
  const s = Math.max(0, Math.floor((now - parseIsoUtc(from).getTime()) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function Running({ t }: { t: TailoringSummary }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const i = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(i);
  }, []);
  const steps = t.send_requested ? [...STEPS, "Sending to Telegram"] : STEPS;
  const label = t.status === "queued" ? "Queued" : t.progress || "Starting";
  const at = steps.indexOf(t.progress);
  return (
    <section aria-label="Tailoring progress" className="mx-auto mt-16 max-w-xl">
      <div className="flex items-baseline justify-between gap-4">
        <p className="font-mono text-[14px] font-medium" role="status" aria-live="polite">
          <span className="text-blue">{t.status === "queued" ? "QUEUED" : "RUNNING"}</span>
          <span className="text-ink-muted"> · </span>
          {label}
        </p>
        <span className="num text-[12px] text-ink-muted">{elapsed(t.started_at ?? t.created_at, now)}</span>
      </div>
      <div className="relative mt-3 h-0.5 overflow-hidden bg-rule" aria-hidden>
        <div className="indeterminate absolute inset-y-0 w-1/3 bg-blue" />
      </div>
      <ol className="mt-6 space-y-2">
        {steps.map((s, i) => (
          <li
            key={s}
            className={cn(
              "flex items-center gap-3 font-mono text-[12.5px]",
              i < at ? "text-ink" : i === at ? "text-blue" : "text-ink-muted",
            )}
          >
            <span
              aria-hidden
              className={cn("size-2", i < at ? "bg-ink" : i === at ? "bg-blue" : "border border-input")}
            />
            {s}
          </li>
        ))}
      </ol>
      <p className="mt-8 text-[14px] text-ink-muted">
        Usually takes 1 to 3 minutes. You can leave this page; the run keeps going.
      </p>
    </section>
  );
}

function Chips({ title, items, tone }: { title: string; items: string[]; tone: "match" | "gap" }) {
  return (
    <section className="border-t border-rule pt-4">
      <p className="kicker text-ink-muted">{title}</p>
      {items.length ? (
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {items.map((k) => (
            <li
              key={k}
              className={cn(
                "px-2 py-1 font-mono text-[11.5px] leading-none",
                tone === "match" ? "border border-blue text-blue" : "border border-chip bg-chip text-ink",
              )}
            >
              {k}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-[13px] text-ink-muted">None</p>
      )}
    </section>
  );
}

function Done({ t, jobId, onRegenerate, regenerating }: { t: TailoringDetail; jobId: number; onRegenerate: () => void; regenerating: boolean }) {
  const qc = useQueryClient();
  const runCurrent = t.current;
  const needCurrent = !runCurrent?.ready;
  const { data: fallback } = useQuery({
    queryKey: ["resume-current"],
    queryFn: api.resumeCurrent,
    enabled: needCurrent,
    refetchInterval: (q) => (q.state.data?.ready ? false : 3000),
  });
  const current = runCurrent?.ready ? runCurrent : fallback;
  const send = useMutation({
    mutationFn: () => api.sendTailoring(t.id),
    onSuccess: () => {
      toast.success("Sent to Telegram");
      qc.invalidateQueries({ queryKey: ["tailoring", t.id] });
      qc.invalidateQueries({ queryKey: ["tailorings", jobId] });
    },
    onError: (e: Error) => toast.error(errMsg(e)),
  });
  const sentAt = send.data?.sent_at ?? t.sent_at;
  const regenLetter = useMutation({
    mutationFn: () => api.regenerateCoverLetter(t.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tailoring", t.id] }),
    onError: (e: Error) => toast.error(errMsg(e)),
  });
  // Toast once when a letter regeneration finishes while the page is open.
  const regenStatus = t.cover_letter_regen?.status;
  const [lastRegen, setLastRegen] = useState(regenStatus);
  if (regenStatus !== lastRegen) {
    setLastRegen(regenStatus);
    if ((lastRegen === "queued" || lastRegen === "running") && regenStatus === "done") toast.success("New cover letter ready");
  }
  const rm = t.resume_matcher;
  const prep = rm?.status === "done" ? rm.interview_prep : null;
  const hasQuestions = !!(prep?.resume_questions?.length || prep?.project_follow_ups?.length);

  return (
    <>
      <div className="mt-5 flex flex-wrap items-center gap-2 border-b border-rule pb-5">
        {t.files && (
          <>
            <Button render={<a href={t.files.resume_pdf} download />}>Download resume PDF</Button>
            <Button variant="outline" render={<a href={t.files.cover_letter_pdf} download />}>
              Download cover letter PDF
            </Button>
          </>
        )}
        <Button variant="outline" onClick={() => send.mutate()} disabled={send.isPending}>
          {send.isPending ? "Sending…" : sentAt ? "Send again" : "Send to Telegram"}
        </Button>
        {sentAt && <span className="num text-[12px] text-blue">Sent {adelaideTime(sentAt)}</span>}
        <Button variant="ghost" className="ml-auto" onClick={onRegenerate} disabled={regenerating}>
          {regenerating ? "Starting…" : "Regenerate all"}
        </Button>
      </div>

      {t.ats?.tailored && <AtsBlock ats={t.ats} tid={t.id} rm={rm} />}

      <div className="mt-8 grid gap-10 min-[1440px]:grid-cols-[minmax(0,1fr)_400px]">
        <PagePreviews
          current={current?.ready ? current.page_urls : []}
          tailored={t.files?.resume_pages ?? []}
          currentPending={current?.error ?? "Building current resume…"}
        />
        <aside className="space-y-6 min-[1440px]:h-[calc(100dvh-11rem)] min-[1440px]:overflow-y-auto min-[1440px]:pr-1">
          {t.warnings.length > 0 && (
            <div className="bg-chip px-4 py-3 text-[13.5px] leading-relaxed">
              <p className="kicker text-ink">Reverted to your original wording</p>
              <p className="mt-1 text-[12.5px] text-ink-muted">Where an AI edit broke a rule, the original was kept:</p>
              <ul className="mt-1.5 list-disc space-y-1 pl-5 text-ink">
                {t.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>
          )}
          <ChangesPanel changes={t.changes} counts={t.change_counts} />
          <Chips title="Keywords matched" items={t.keywords_matched} tone="match" />
          <Chips title="Gaps" items={t.gaps} tone="gap" />
        </aside>
      </div>

      {t.cover_letter && (
        <CoverLetterSection
          letter={t.cover_letter}
          pages={t.files?.cover_letter_pages ?? []}
          regen={t.cover_letter_regen ?? null}
          onRegenerate={() => regenLetter.mutate()}
          starting={regenLetter.isPending}
        />
      )}
      {prep && hasQuestions && <InterviewPrepSection prep={prep} />}
      {rm?.status === "done" && rm.outreach_message && (
        <OutreachSection message={rm.outreach_message} recruiter={t.job.contact_name} />
      )}
    </>
  );
}

export function TailorPage() {
  const jobId = Number(useParams().id);
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();

  const { data: job } = useQuery({ queryKey: ["job", jobId], queryFn: () => api.job(jobId), enabled: !!jobId });
  const { data: runs = [], isLoading: runsLoading } = useQuery({
    queryKey: ["tailorings", jobId],
    queryFn: () => api.tailorings(jobId),
    enabled: !!jobId,
  });
  const runId = Number(params.get("run")) || runs[0]?.id || null;
  const { data: t, error } = useQuery({
    queryKey: ["tailoring", runId],
    queryFn: () => api.tailoring(runId!),
    enabled: runId !== null,
    refetchInterval: (q) =>
      isActive(q.state.data?.status) || letterBusy(q.state.data) ? 2000 : rmBusy(q.state.data) ? 4000 : false,
  });

  // Keep the run list (and the job detail's status line) fresh when a run finishes.
  const status = t?.status;
  useEffect(() => {
    if (status) qc.invalidateQueries({ queryKey: ["tailorings", jobId] });
  }, [status, jobId, qc]);

  const selectRun = (id: number) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set("run", String(id));
        return next;
      },
      { replace: true },
    );

  const regenerate = useMutation({
    mutationFn: () => api.tailor(jobId),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["tailorings", jobId] });
      selectRun(r.tailoring_id);
    },
    onError: (e: Error) => toast.error(errMsg(e)),
  });

  const head = t?.job ?? job;
  const recruiter = t?.job.contact_name ?? job?.contact_name;

  return (
    <div className="mx-auto w-full max-w-[1680px] px-5 py-6 lg:px-8 lg:py-8">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
        <Link to={`/?job=${jobId}`} className="kicker text-blue hover:underline">
          <span aria-hidden>←</span> Back to job
        </Link>
        <Link to="/resumes" className="kicker text-ink-muted hover:text-blue hover:underline">
          All resumes
        </Link>
      </div>

      <header className="mt-4 flex flex-wrap items-end justify-between gap-x-10 gap-y-4 border-b-2 border-ink pb-5">
        <div className="min-w-0 max-w-4xl">
          <p className="kicker text-ink-muted">Tailored resume</p>
          <h1 className="display mt-2 text-[30px] leading-[1.05] text-balance sm:text-[40px]">{head?.title ?? "…"}</h1>
          {head && (
            <p className="mt-2 text-[15px]">
              <span className="font-semibold">{head.company}</span>
              <span className="text-ink-faint"> · </span>
              <span className="text-ink-muted">{WORK_TYPE_CAPS[head.work_type]}</span>
              {recruiter && (
                <>
                  <span className="text-ink-faint"> · </span>
                  <span className="text-ink-muted">Recruiter {recruiter}</span>
                </>
              )}
            </p>
          )}
        </div>
        {runs.length > 0 && (
          <label className="grid w-full gap-1.5 sm:w-auto">
            <span className="kicker text-ink-muted">Run</span>
            <select
              className="field h-9 w-full px-2 font-mono text-[12.5px] outline-none sm:min-w-64"
              value={runId ?? ""}
              onChange={(e) => selectRun(Number(e.target.value))}
            >
              {runs.map((r, i) => (
                <option key={r.id} value={r.id}>
                  #{r.id} · {adelaideTime(r.created_at)} · {r.status}
                  {i === 0 ? " · latest" : ""}
                </option>
              ))}
            </select>
          </label>
        )}
      </header>

      {error ? (
        <p className="mt-10 bg-chip px-4 py-3 text-sm">{errMsg(error)}</p>
      ) : runsLoading ? (
        <p className="kicker mt-10 text-ink-muted">Loading…</p>
      ) : !runs.length && runId === null ? (
        <div className="mx-auto mt-16 max-w-lg text-center">
          <p className="display text-[26px]">No tailored resume yet.</p>
          <p className="mt-2 text-[15px] text-ink-muted">
            Rewrites your summary, bullets and skill order for this ad (no new facts) and drafts a cover letter.
          </p>
          <Button className="mt-6" onClick={() => regenerate.mutate()} disabled={regenerate.isPending}>
            Tailor resume
          </Button>
        </div>
      ) : !t ? (
        <p className="kicker mt-10 text-ink-muted">Loading run…</p>
      ) : isActive(t.status) ? (
        <Running t={t} />
      ) : t.status === "failed" ? (
        <section className="mx-auto mt-14 max-w-xl">
          <p className="kicker text-ink">Tailoring failed</p>
          <pre className="mt-3 overflow-x-auto bg-chip px-4 py-3 font-mono text-[12.5px] whitespace-pre-wrap text-ink">
            {t.error || "Unknown error"}
          </pre>
          <Button className="mt-5" onClick={() => regenerate.mutate()} disabled={regenerate.isPending}>
            Try again
          </Button>
        </section>
      ) : (
        <Done t={t} jobId={jobId} onRegenerate={() => regenerate.mutate()} regenerating={regenerate.isPending} />
      )}
    </div>
  );
}
