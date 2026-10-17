import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { api, errMsg } from "@/lib/api";
import { ago } from "@/lib/format";

/** "Tailor resume" primary action plus a one-line status of the latest run. */
export function TailorAction({ jobId, children }: { jobId: number; children?: React.ReactNode }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data: runs = [] } = useQuery({
    queryKey: ["tailorings", jobId],
    queryFn: () => api.tailorings(jobId),
    refetchInterval: (q) => {
      const s = q.state.data?.[0]?.status;
      return s === "queued" || s === "running" ? 5000 : false;
    },
  });
  const start = useMutation({
    mutationFn: () => api.tailor(jobId),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["tailorings", jobId] });
      navigate(`/jobs/${jobId}/tailor?run=${r.tailoring_id}`);
    },
    onError: (e: Error) => toast.error(errMsg(e)),
  });
  const latest = runs[0];
  const href = latest ? `/jobs/${jobId}/tailor?run=${latest.id}` : `/jobs/${jobId}/tailor`;

  return (
    <div className="w-full">
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => start.mutate()} disabled={start.isPending}>
          {start.isPending ? "Starting…" : "Tailor resume"}
        </Button>
        {children}
      </div>
      {latest && (
        <p className="mt-2 font-mono text-[11.5px] text-ink-muted">
          {latest.status === "done" ? (
            <>Tailored {ago(latest.finished_at ?? latest.created_at)}</>
          ) : latest.status === "failed" ? (
            <>Last run failed</>
          ) : (
            <>
              Tailoring… <span className="text-blue">{latest.progress || "Queued"}</span>
            </>
          )}
          <span className="text-ink-faint"> · </span>
          <Link to={href} className="text-blue underline-offset-4 hover:underline">
            View
          </Link>
        </p>
      )}
    </div>
  );
}
