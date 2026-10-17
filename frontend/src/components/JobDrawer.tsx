import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import DOMPurify from "dompurify";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
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
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["job", job?.id], queryFn: () => api.job(job!.id), enabled: !!job });
  const [notes, setNotes] = useState("");
  useEffect(() => setNotes(data?.notes ?? ""), [data?.notes]);

  const done = (msg: string) => {
    toast.success(msg);
    qc.invalidateQueries({ queryKey: ["jobs"] });
    qc.invalidateQueries({ queryKey: ["job", job?.id] });
  };
  const fail = (e: Error) => toast.error(e.message.includes("401") ? "Set the write token first" : e.message);
  const patch = useMutation({
    mutationFn: (body: { status?: JobStatus; notes?: string }) => api.patchJob(job!.id, body),
    onSuccess: () => done("Saved"),
    onError: fail,
  });
  const unexclude = useMutation({
    mutationFn: (allow: boolean) => api.unexclude(job!.id, allow),
    onSuccess: () => {
      done("Moved to jobs");
      onClose();
    },
    onError: fail,
  });

  return (
    <Sheet open={!!job} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
        {job && (
          <>
            <SheetHeader>
              <SheetTitle className="flex items-start gap-3">
                <ScoreBadge score={job.final_score} />
                <span>{job.title}</span>
              </SheetTitle>
              <p className="text-sm text-muted-foreground">
                {job.company} · {job.location} · {WORK_TYPE_LABEL[job.work_type]}
                {job.salary_label ? ` · ${job.salary_label}` : ""}
              </p>
            </SheetHeader>
            <div className="space-y-4 px-4 pb-8">
              <div className="flex flex-wrap gap-1">
                {job.matched_skills.map((s) => (
                  <Badge key={s} variant="secondary">
                    {s}
                  </Badge>
                ))}
              </div>
              <p className="text-sm">
                Rule {job.rule_score}
                {job.llm_score !== null && ` · AI ${job.llm_score}`}
                {job.llm_note && <span className="text-muted-foreground"> — "{job.llm_note}"</span>}
              </p>
              {job.excluded && (
                <div className="rounded-md border border-destructive/40 p-3 text-sm">
                  {Object.entries(job.snippets).map(([reason, snippet]) => (
                    <p key={reason}>
                      <b>{reason}</b>: …{snippet}…
                    </p>
                  ))}
                  <div className="mt-2 flex gap-2">
                    <Button size="sm" variant="outline" onClick={() => unexclude.mutate(false)}>
                      Un-exclude
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => unexclude.mutate(true)}>
                      Un-exclude + allowlist {job.company}
                    </Button>
                  </div>
                </div>
              )}
              <div className="flex flex-wrap gap-2">
                <Button size="sm" render={<a href={job.url} target="_blank" rel="noreferrer" />}>
                  Open on {job.source === "seek" ? "SEEK" : "Jora"}
                </Button>
                {(["saved", "applied", "hidden", "new"] as JobStatus[]).map((s) => (
                  <Button key={s} size="sm" variant={job.status === s ? "default" : "outline"} onClick={() => patch.mutate({ status: s })}>
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
                dangerouslySetInnerHTML={{ __html: highlight(data?.description_html || data?.teaser || "", job.matched_skills) }}
              />
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
