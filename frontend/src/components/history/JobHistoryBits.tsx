import { useMutation } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { api, errMsg } from "@/lib/api";
import { adelaideTime, ago } from "@/lib/format";
import type { ApplicationSummary, InteractionKind, PriorApplication } from "@/lib/types";
import { QuickLog, StageSelect, StageTag, useInvalidateHistory } from "./shared";

/** "<Company> already has your resume" box for the job detail pane. */
export function PriorApplicationsBox({ company, prior }: { company: string; prior: PriorApplication[] }) {
  return (
    <aside aria-label="Previous applications" className="mt-5 border border-ink px-4 py-3">
      <p className="text-[14px] font-semibold">
        <span aria-hidden className="mr-2 inline-block size-2 translate-y-[-1px] bg-blue" />
        {company} already has your resume
      </p>
      <ul className="mt-1.5 space-y-1">
        {prior.map((p) => (
          <li key={p.application_id} className="flex flex-wrap items-baseline gap-x-2 text-[13.5px]">
            <span>{p.title}</span>
            <span className="text-ink-faint">·</span>
            <span className="num text-[12px] text-ink-muted">{ago(p.applied_at)}</span>
            <span className="text-ink-faint">·</span>
            <StageTag stage={p.stage} />
          </li>
        ))}
      </ul>
      <Link to="/history?tab=companies" className="kicker mt-2 inline-block text-[10.5px] text-blue hover:underline">
        View in History
      </Link>
    </aside>
  );
}

/** APPLICATION row: stage select + applied date for a job that has been applied to. */
export function ApplicationRow({ jobId, app }: { jobId: number; app: ApplicationSummary }) {
  const invalidate = useInvalidateHistory();
  const patch = useMutation({
    mutationFn: (stage: ApplicationSummary["stage"]) => api.patchApplication(app.id, { stage }),
    onSuccess: () => {
      toast.success("Stage updated");
      invalidate(jobId);
    },
    onError: (e: Error) => toast.error(errMsg(e)),
  });
  return (
    <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2 border-y border-rule py-3">
      <span className="kicker w-24 text-ink-muted">Application</span>
      <StageSelect value={app.stage} onChange={(s) => patch.mutate(s)} label="Application stage" disabled={patch.isPending} />
      <span className="num text-[12px] text-ink-muted">Applied {adelaideTime(app.applied_at)}</span>
      <Link to="/history" className="kicker ml-auto text-[10.5px] text-blue hover:underline">
        History
      </Link>
    </div>
  );
}

const RECRUITER_KINDS: InteractionKind[] = ["call", "email", "linkedin_invite"];

/** Quick log for the ad's recruiter (creates/links the contact server-side). */
export function RecruiterQuickLog({ jobId }: { jobId: number }) {
  const invalidate = useInvalidateHistory();
  const log = useMutation({
    mutationFn: (kind: InteractionKind) => api.jobContactLog(jobId, kind),
    onSuccess: () => invalidate(jobId),
    onError: (e: Error) => toast.error(errMsg(e)),
  });
  return (
    <div className="mt-3">
      <QuickLog kinds={RECRUITER_KINDS} withNote={false} pending={log.isPending} onLog={(kind) => log.mutateAsync(kind)} />
    </div>
  );
}
