import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { HistoryEvent, InteractionKind } from "@/lib/types";
import { parseIsoUtc } from "@/lib/utils";
import { KIND_PAST, stageLabel } from "./shared";

const TZ = "Australia/Adelaide";
const dayKey = (iso: string) => parseIsoUtc(iso).toLocaleDateString("en-CA", { timeZone: TZ });
const dayLabel = (iso: string) =>
  parseIsoUtc(iso).toLocaleDateString("en-AU", { weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: TZ });
const time = (iso: string) => parseIsoUtc(iso).toLocaleTimeString("en-AU", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: TZ });

function describe(e: HistoryEvent): { head: string; rest: string[] } {
  const where = [e.title, e.company].filter((x): x is string => !!x);
  if (e.type === "event") {
    if (e.kind === "created") return { head: "Applied", rest: where };
    if (e.kind === "stage_changed")
      return { head: `Stage ${e.from_stage ? `${stageLabel(e.from_stage)} ` : ""}→ ${stageLabel(e.to_stage ?? "")}`, rest: where };
    return { head: "Note", rest: where };
  }
  const verb = KIND_PAST[e.kind as InteractionKind] ?? e.kind;
  return { head: `${verb} ${e.contact_name ?? ""}`.trim(), rest: e.title ? where : e.company ? [e.company] : [] };
}

export function TimelineTab() {
  const { data = [], isLoading } = useQuery({ queryKey: ["history", 200], queryFn: () => api.history(200) });
  const days: { key: string; label: string; events: HistoryEvent[] }[] = [];
  for (const e of data) {
    const key = dayKey(e.at);
    const last = days[days.length - 1];
    if (last?.key === key) last.events.push(e);
    else days.push({ key, label: dayLabel(e.at), events: [e] });
  }
  return (
    <div className="max-w-3xl">
      {days.map((d) => (
        <section key={d.key} aria-label={d.label} className="mt-6 first:mt-0">
          <h3 className="kicker border-b-2 border-ink pb-1.5 text-ink">{d.label}</h3>
          <ol className="divide-y divide-rule">
            {d.events.map((e, i) => {
              const { head, rest } = describe(e);
              const stage = e.type === "event" && e.kind === "stage_changed";
              return (
                <li key={`${e.at}-${i}`} className="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-x-3 py-2.5">
                  <span className="num pt-0.5 text-[12px] text-ink-muted">{time(e.at)}</span>
                  <p className="text-[14px] leading-snug">
                    <span className={stage && e.to_stage === "interview" ? "font-semibold text-blue" : "font-semibold"}>{head}</span>
                    {rest.map((r) => (
                      <span key={r}>
                        <span className="text-ink-faint"> · </span>
                        {r}
                      </span>
                    ))}
                    {e.note && <span className="mt-0.5 block text-[13px] text-ink-muted">{e.note}</span>}
                  </p>
                </li>
              );
            })}
          </ol>
        </section>
      ))}
      {!isLoading && !data.length && <p className="py-12 text-center text-sm text-ink-muted">Nothing has happened yet.</p>}
    </div>
  );
}
