import { useQuery } from "@tanstack/react-query";
import { Page, PageHead } from "@/components/PageHead";
import { api } from "@/lib/api";
import { cn, parseIsoUtc } from "@/lib/utils";

const fmt = (iso: string | null) =>
  iso
    ? parseIsoUtc(iso).toLocaleString("en-AU", {
        timeZone: "Australia/Adelaide",
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : "—";

const TH = "kicker px-3 py-2 text-left text-[10.5px] font-medium text-ink-muted";

export function RunsPage() {
  const { data = [], isLoading } = useQuery({ queryKey: ["runs"], queryFn: api.runs, refetchInterval: 30_000 });
  return (
    <Page>
      <PageHead kicker="Press log" title="Runs" dek="Every crawl, what each source returned, and what went out to Telegram. Refreshes every 30 seconds." />
      <div className="mt-6 overflow-x-auto">
        <table className="num w-full min-w-[720px] border-collapse text-[12.5px]">
          <thead>
            <tr className="border-b border-ink">
              <th className={TH}>Started · Adelaide</th>
              <th className={TH}>Sources · new/found · requests</th>
              <th className={cn(TH, "text-right")}>New</th>
              <th className={cn(TH, "text-right")}>Notified</th>
              <th className={TH}>AI</th>
              <th className={TH}>Error</th>
            </tr>
          </thead>
          <tbody>
            {data.map((r) => (
              <tr key={r.id} className="border-b border-rule align-top hover:bg-ink/[0.03]">
                <td className="px-3 py-2.5 whitespace-nowrap">{fmt(r.started_at)}</td>
                <td className="px-3 py-2.5">
                  <div className="flex flex-col gap-0.5">
                    {Object.entries(r.source_status).map(([name, st]) => (
                      <span key={name} title={st.error ?? ""} className={st.status === "ok" ? "text-ink" : "text-signal"}>
                        <span className="inline-block w-12 uppercase">{name}</span>
                        {st.new}/{st.found} · {st.requests} req
                        {st.blocked ? ` · ${st.blocked}×403` : ""}
                        {st.status !== "ok" && <span className="kicker ml-2 text-[10px]">degraded</span>}
                      </span>
                    ))}
                  </div>
                </td>
                <td className={cn("px-3 py-2.5 text-right", r.new_jobs > 0 ? "font-medium" : "text-ink-faint")}>{r.new_jobs}</td>
                <td className={cn("px-3 py-2.5 text-right", r.notified > 0 ? "" : "text-ink-faint")}>{r.notified}</td>
                <td className="px-3 py-2.5 text-ink-muted">{r.llm_provider ?? "rules"}</td>
                <td className="max-w-xs truncate px-3 py-2.5 text-signal" title={r.error ?? ""}>
                  {r.error}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!isLoading && !data.length && <p className="py-12 text-center text-sm text-ink-muted italic">No runs recorded yet.</p>}
      </div>
    </Page>
  );
}
