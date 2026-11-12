import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, errMsg } from "@/lib/api";
import { WORK_TYPE_CAPS } from "@/lib/format";
import type { FunnelResult, FunnelRow, WorkType } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Groups with fewer applications than this are shown, but greyed: too few to compare. */
export const MIN_N = 5;

const WINDOWS = [
  { days: 0, label: "All time" },
  { days: 90, label: "90 days" },
  { days: 30, label: "30 days" },
] as const;

const SOURCE_LABEL: Record<string, string> = {
  seek: "SEEK",
  jora: "Jora",
  linkedin: "LinkedIn",
  indeed: "Indeed",
  radar: "Company radar",
  manual: "Added manually",
};
const EMPLOYER_LABEL: Record<string, string> = { agency: "Recruitment agency", direct: "Direct employer" };
const CALL_LABEL: Record<string, string> = {
  called: "Called the recruiter",
  voicemail: "Left a voicemail only",
  "not called": "Didn't call",
};

const SECTIONS: { key: keyof Omit<FunnelResult, "total">; title: string; label: (l: string) => string; note?: string }[] = [
  { key: "by_source", title: "By source", label: (l) => SOURCE_LABEL[l] ?? l },
  { key: "by_employer", title: "Agency or direct", label: (l) => EMPLOYER_LABEL[l] ?? l },
  { key: "by_work_type", title: "By work type", label: (l) => WORK_TYPE_CAPS[l as WorkType] ?? l },
  {
    key: "by_call",
    title: "Called before applying",
    label: (l) => CALL_LABEL[l] ?? l,
    note: "A call logged with the job's recruiter before applying, or within a day after.",
  },
];

export const pct = (r: number | null) => (r === null ? "—" : `${Math.round(r * 100)}%`);

const TH = "kicker px-3 py-2 text-[10.5px] font-medium text-ink-muted";

function StageStrip({ total }: { total: FunnelRow }) {
  const steps: { label: string; n: number }[] = [
    { label: "Applied", n: total.applied },
    { label: "Responded", n: total.responded },
    { label: "Interview", n: total.interview },
    { label: "Offer", n: total.offer },
  ];
  return (
    <dl aria-label="Funnel" className="grid grid-cols-2 border-y-2 border-ink sm:grid-cols-4">
      {steps.map((s, i) => (
        <div key={s.label} className={cn(
            "border-rule px-4 py-4",
            i % 2 === 1 && "border-l",
            i >= 2 && "border-t sm:border-t-0",
            i === 2 && "sm:border-l",
          )}>
          <dt className="kicker text-[10.5px] text-ink-muted">{s.label}</dt>
          <dd className="num mt-1 text-[40px] leading-none font-medium">{s.n}</dd>
          {i > 0 && (
            <dd className="num mt-1.5 text-[12px] text-ink-muted">
              {total.applied ? `${pct(s.n / total.applied)} of applied` : "—"}
            </dd>
          )}
        </div>
      ))}
    </dl>
  );
}

function Breakdown({ title, rows, label, note }: { title: string; rows: FunnelRow[]; label: (l: string) => string; note?: string }) {
  return (
    <section aria-label={title} className="mt-9">
      <h3 className="kicker border-b-2 border-ink pb-1.5 text-ink">{title}</h3>
      {note && <p className="mt-1.5 text-[12.5px] text-ink-muted">{note}</p>}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[620px] table-fixed border-collapse text-[13.5px]">
          <caption className="sr-only">{title}</caption>
          <colgroup>
            <col className="w-[28%]" />
          </colgroup>
          <thead>
            <tr className="border-b border-ink">
              <th className={cn(TH, "text-left")}>Group</th>
              <th className={cn(TH, "text-right")}>Applied</th>
              <th className={cn(TH, "text-right")}>Responded</th>
              <th className={cn(TH, "text-right")}>Response rate</th>
              <th className={cn(TH, "text-right")}>Interview</th>
              <th className={cn(TH, "text-right")}>Interview rate</th>
              <th className={cn(TH, "text-right")}>Offer</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const low = r.applied < MIN_N;
              return (
                <tr key={r.label} className={cn("border-b border-rule", low && "text-ink-muted")}>
                  <th scope="row" className="px-3 py-2.5 text-left font-medium">
                    {label(r.label)}
                    {low && <span className="kicker ml-2 text-[9.5px] text-ink-muted">low n</span>}
                  </th>
                  <td className="num px-3 py-2.5 text-right">n={r.applied}</td>
                  <td className="num px-3 py-2.5 text-right">{r.responded}</td>
                  <td className={cn("num px-3 py-2.5 text-right", !low && "text-ink font-medium")}>{pct(r.response_rate)}</td>
                  <td className="num px-3 py-2.5 text-right">{r.interview}</td>
                  <td className={cn("num px-3 py-2.5 text-right", !low && "text-ink font-medium")}>{pct(r.interview_rate)}</td>
                  <td className="num px-3 py-2.5 text-right">{r.offer}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!rows.length && <p className="py-4 text-[13px] text-ink-muted">No applications in this window.</p>}
      </div>
    </section>
  );
}

export function FunnelTab() {
  const [days, setDays] = useState<number>(0);
  const { data, isLoading, error } = useQuery({
    queryKey: ["funnel", days],
    queryFn: () => api.funnel(days || undefined),
    placeholderData: (p) => p,
  });
  return (
    <div className="max-w-5xl">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-[14px] text-ink-muted">
          Responded counts any answer (screening, interview, offer, a rejection, or a logged reply). Stages count once reached, so an
          interview that ended in a rejection is still an interview.
        </p>
        <div className="flex gap-1.5" role="group" aria-label="Window">
          {WINDOWS.map((w) => (
            <button
              key={w.days}
              type="button"
              aria-pressed={days === w.days}
              onClick={() => setDays(w.days)}
              className={cn(
                "h-8 border px-2.5 font-mono text-[11px] tracking-[0.06em] uppercase",
                days === w.days ? "border-ink bg-ink text-white" : "border-input text-ink hover:border-ink",
              )}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>
      {error && <p className="py-6 text-[13.5px] text-ink-muted">{errMsg(error)}</p>}
      {isLoading && <p className="kicker py-6 text-ink-muted">Loading…</p>}
      {data && (
        <div className="mt-6">
          <StageStrip total={data.total} />
          {data.total.applied > 0 && data.total.applied < MIN_N * 2 && (
            <p className="mt-2 text-[12.5px] text-ink-muted">
              n={data.total.applied} so far: treat every rate below as a hint, not a result.
            </p>
          )}
          {SECTIONS.map((s) => (
            <Breakdown key={s.key} title={s.title} rows={data[s.key]} label={s.label} note={s.note} />
          ))}
          <p className="mt-4 font-mono text-[11px] text-ink-muted">
            Groups under {MIN_N} applications are greyed and marked low n: too few to compare.
          </p>
        </div>
      )}
    </div>
  );
}
