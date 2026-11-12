import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, errMsg } from "@/lib/api";
import { ago } from "@/lib/format";
import type { CallScript as Script } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CopyButton } from "./CopyButton";
import { smallBtn } from "./history/shared";

/** Everything on one clipboard: pitch first, then the numbered questions. */
export function scriptText(s: Pick<Script, "pitch" | "questions">): string {
  return [s.pitch, "", ...s.questions.map((q, i) => `${i + 1}. ${q}`)].join("\n");
}

function sourceLine(s: Script): string {
  if (!s.cached) return "Template · not saved";
  const when = s.created_at ? ` · ${ago(s.created_at)}` : "";
  return s.source === "llm" ? `AI, checked against your resume${when}` : `Template${when}`;
}

/**
 * Call script for the ad's recruiter: a ~20 s pitch and three questions for this job. Opens with an
 * instant template (GET); "Write with AI" asks the server to generate and cache one (POST).
 */
export function CallScript({ jobId }: { jobId: number }) {
  const qc = useQueryClient();
  const key = ["call-script", jobId];
  const { data, error, isLoading } = useQuery({ queryKey: key, queryFn: () => api.callScript(jobId) });
  const generate = useMutation({
    mutationFn: (refresh: boolean) => api.generateCallScript(jobId, refresh),
    onSuccess: (s) => {
      qc.setQueryData(key, s);
      if (s.source === "template") toast.message("AI unavailable; kept the template script");
    },
    onError: (e: Error) => toast.error(errMsg(e)),
  });

  const ai = data?.cached && data.source === "llm";
  return (
    <section aria-labelledby={`call-script-${jobId}`} className="mt-5 border-t border-rule pt-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
        <p id={`call-script-${jobId}`} className="kicker text-ink">
          Call script
          {data && <span className="ml-3 font-mono text-[10.5px] tracking-[0.06em] text-ink-muted normal-case">{sourceLine(data)}</span>}
        </p>
        <div className="flex items-center gap-1.5">
          {data && <CopyButton text={scriptText(data)} label="Copy call script" className="h-8 lg:h-8" />}
          <button
            type="button"
            className={smallBtn}
            disabled={!data || generate.isPending}
            onClick={() => generate.mutate(!!ai)}
            title={ai ? "Write a fresh one" : "Tailor the pitch and questions to this ad with AI"}
          >
            {generate.isPending ? "Writing…" : ai ? "Rewrite" : "Write with AI"}
          </button>
        </div>
      </div>

      {isLoading && <p className="kicker mt-3 text-ink-muted">Preparing script…</p>}
      {error && <p className="mt-3 text-[13.5px] text-ink-muted">{errMsg(error)}</p>}

      {data && (
        <div className={cn("transition-opacity", generate.isPending && "opacity-50")} aria-busy={generate.isPending}>
          <div className="mt-3 flex items-start justify-between gap-3 border-l-2 border-blue pl-4">
            <div className="min-w-0">
              <p className="kicker text-[10.5px] text-blue">Pitch · about 20 seconds</p>
              <p className="mt-1.5 text-[15px] leading-relaxed text-ink">{data.pitch}</p>
            </div>
            <CopyButton text={data.pitch} label="Copy pitch" />
          </div>

          <p className="kicker mt-4 text-[10.5px] text-ink-muted">Ask</p>
          <ol aria-label="Questions to ask" className="mt-1 divide-y divide-rule border-y border-rule">
            {data.questions.map((q, i) => (
              <li key={i} className="grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-2 py-2 text-[14px] leading-snug">
                <span className="num pt-px text-[12px] text-ink-muted">{String(i + 1).padStart(2, "0")}</span>
                <span>{q}</span>
              </li>
            ))}
          </ol>

          {data.warnings.length > 0 && (
            <ul aria-label="Script notes" className="mt-2 space-y-0.5">
              {data.warnings.map((w) => (
                <li key={w} className="font-mono text-[11px] text-ink-muted">
                  {w}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
