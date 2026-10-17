import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import DOMPurify from "dompurify";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { api, errMsg } from "@/lib/api";
import { type Job, type JobStatus, WORK_TYPE_LABEL } from "@/lib/types";
import { ScoreBadge } from "./ScoreBadge";

export function highlight(html: string, skills: string[]): string {
  const clean = DOMPurify.sanitize(html);
  if (!skills.length) return clean;
  const escaped = skills.map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const re = new RegExp(`(?<![\\w#+.])(${escaped.join("|")})(?![\\w#+])`, "gi");
  return clean.replace(/>([^<]+)</g, (_m, text: string) => `>${text.replace(re, "<mark>$1</mark>")}<`);
}

export function JobDrawer({ job, onClose }: { job: Job | null; onClose: () => void }) {
  return (
    <Sheet open={!!job} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
        {job && <JobDrawerBody key={job.id} job={job} onClose={onClose} />}
      </SheetContent>
    </Sheet>
  );
}

function JobDrawerBody({ job, onClose }: { job: Job; onClose: () => void }) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["job", job.id], queryFn: () => api.job(job.id) });
  // `data` (the fetched detail) wins once loaded so status/notes reflect the latest PATCH;
  // `job` (the row passed in) is only the fallback shown before the fetch resolves.
  const view = data ?? job;
  const [notes, setNotes] = useState(view.notes);
  useEffect(() => setNotes(view.notes), [view.notes]);

  const done = (msg: string) => {
    toast.success(msg);
    qc.invalidateQueries({ queryKey: ["jobs"] });
    qc.invalidateQueries({ queryKey: ["job", job.id] });
  };
  const fail = (e: Error) => toast.error(errMsg(e));
  const patch = useMutation({
    mutationFn: (body: { status?: JobStatus; notes?: string }) => api.patchJob(job.id, body),
    onSuccess: () => done("Saved"),
    onError: fail,
  });
  const unexclude = useMutation({
    mutationFn: (allow: boolean) => api.unexclude(job.id, allow),
    onSuccess: (_result, allow) => {
      done("Moved to jobs");
      if (allow) qc.invalidateQueries({ queryKey: ["settings"] });
      onClose();
    },
    onError: fail,
  });

  return (
    <>
      <SheetHeader>
        <SheetTitle className="flex items-start gap-3">
          <ScoreBadge score={view.final_score} />
          <span>{view.title}</span>
        </SheetTitle>
        <p className="text-sm text-muted-foreground">
          {view.company} · {view.location} · {WORK_TYPE_LABEL[view.work_type]}
          {view.salary_label ? ` · ${view.salary_label}` : ""}
        </p>
      </SheetHeader>
      <div className="space-y-4 px-4 pb-8">
        <div className="flex flex-wrap gap-1">
          {view.matched_skills.map((s) => (
            <Badge key={s} variant="secondary">
              {s}
            </Badge>
          ))}
        </div>
        <p className="text-sm">
          Rule {view.rule_score}
          {view.llm_score !== null && ` · AI ${view.llm_score}`}
          {view.llm_note && <span className="text-muted-foreground"> — "{view.llm_note}"</span>}
        </p>
        {view.excluded && (
          <div className="rounded-md border border-destructive/40 p-3 text-sm">
            {Object.entries(view.snippets).map(([reason, snippet]) => (
              <p key={reason}>
                <b>{reason}</b>: …{snippet}…
              </p>
            ))}
            <div className="mt-2 flex gap-2">
              <Button size="sm" variant="outline" onClick={() => unexclude.mutate(false)}>
                Un-exclude
              </Button>
              <Button size="sm" variant="outline" onClick={() => unexclude.mutate(true)}>
                Un-exclude + allowlist {view.company}
              </Button>
            </div>
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" render={<a href={view.url} target="_blank" rel="noreferrer" />}>
            Open on {view.source === "seek" ? "SEEK" : "Jora"}
          </Button>
          {(["saved", "applied", "hidden", "new"] as JobStatus[]).map((s) => (
            <Button key={s} size="sm" variant={view.status === s ? "default" : "outline"} onClick={() => patch.mutate({ status: s })}>
              {s}
            </Button>
          ))}
        </div>
        <div className="space-y-2">
          <Textarea placeholder="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
          <Button size="sm" variant="secondary" onClick={() => patch.mutate({ notes })}>
            Save notes
          </Button>
        </div>
        <article
          className="prose prose-sm max-w-none [&_mark]:bg-yellow-200"
          dangerouslySetInnerHTML={{
            __html: DOMPurify.sanitize(highlight(data?.description_html || data?.teaser || "", view.matched_skills)),
          }}
        />
      </div>
    </>
  );
}
